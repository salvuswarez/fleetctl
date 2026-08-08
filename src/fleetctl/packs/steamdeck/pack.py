"""The Steam Deck pack: probe, capabilities, and a read-only health check."""

from __future__ import annotations

import logging
from functools import cached_property
from importlib import resources
from typing import Any, Mapping

import yaml

from ...core.effects import Capability, Effect
from ...core.inventory.device import Device
from ...core.registry import RegisteredStep
from ...core.state import AppStateSpec
from ...core.transport.base import CommandRunner, Transport
from ...core.workflow.step import DeviceStepContext, StepResult, StepSpec
from ..posix import actions
from ..posix.appmgr import FlatpakAppManager
from ..posix.quirks import PosixQuirks
from ..posix.state import PosixStateManager
from ..posix.transport import SshSettings, SshTransport

LOGGER = logging.getLogger(__name__)

PACK_ID = "steamdeck"
PLATFORM = "linux"

# `ID` from /etc/os-release. `VARIANT_ID=steamdeck` distinguishes a Deck from
# other SteamOS installs, but is not required to claim: SteamOS's quirks come
# from the immutable image, which every variant shares.
DISTRIBUTION = "steamos"

# STATE and APPS are declared because this pack implements both — a Flatpak
# app manager and a POSIX state manager. POWER is offered by the transport but
# not declared: suspend/resume on a Deck behaves unlike a desktop Linux box
# and nothing here has tested a reboot against one.
CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.REACH,
        Capability.FACTS,
        Capability.EXEC,
        Capability.FILES,
        Capability.APPS,
        Capability.STATE,
        Capability.CLEANUP,
    }
)

CHECK = StepSpec(
    id="steamdeck.check",
    summary="Report a Steam Deck's identity, uptime and free space.",
    effect=Effect.READ,
    requires=frozenset({Capability.EXEC, Capability.FACTS}),
    scope="device",
)

MAINTAIN = StepSpec(
    id="steamdeck.maintain",
    summary="Reclaim space on a Steam Deck: prune staging, trim the journal, drop unused runtimes.",
    effect=Effect.DESTRUCTIVE,
    requires=frozenset({Capability.EXEC, Capability.CLEANUP}),
    scope="device",
)


def _load(name: str) -> dict[str, Any]:
    """RETURNS: dict[str, Any]: A parsed data file shipped with this pack."""
    text = resources.files(f"fleetctl.packs.{PACK_ID}.data").joinpath(name).read_text(encoding="utf-8")
    loaded = yaml.safe_load(text)
    return loaded if isinstance(loaded, dict) else {}


class SteamDeckPack:
    """Valve Steam Deck support over SSH.

    Composes `packs/posix`. It is a separate pack rather than a `linux_host`
    variant because SteamOS mounts `/` read-only and keeps applications in
    Flatpak sandboxes — a generic Linux host assumes neither.

    **PARAMETERS:**
        `data` (Mapping[str, Any] | None): Overrides for the shipped data files, keyed by file stem. Defaults to ``None``, meaning use what ships.  <br>
    """

    id = PACK_ID
    platform = PLATFORM
    capabilities = CAPABILITIES
    # Ahead of `linux_host` (50): a Deck answers every generic Linux probe, so
    # whichever pack knows its quirks must get first refusal.
    probe_priority = 20

    def __init__(self, data: Mapping[str, Any] | None = None) -> None:
        self._overrides = dict(data or {})

    @cached_property
    def quirks(self) -> PosixQuirks:
        """RETURNS: PosixQuirks: SteamOS deviations, from `data/quirks.yml`."""
        return PosixQuirks.from_mapping(self._data("quirks"))

    def _data(self, name: str) -> dict[str, Any]:
        override = self._overrides.get(name)
        if isinstance(override, dict):
            return override
        return _load(f"{name}.yml")

    def steps(self) -> list[RegisteredStep]:
        """RETURNS: list[RegisteredStep]: The steps this pack provides."""
        return [
            RegisteredStep(spec=CHECK, run=self.check, provider=PACK_ID),
            RegisteredStep(spec=MAINTAIN, run=self.maintain, provider=PACK_ID),
        ]

    def probe(self, runner: CommandRunner) -> dict[str, str] | None:
        """Claim a host if it reports itself as SteamOS.

        **PARAMETERS:**
            `runner` (CommandRunner): Connection to the candidate host.  <br>

        **RETURNS:**
            `dict[str, str] | None`: Device facts if this pack claims the host, otherwise ``None``.  <br>
        """
        facts = actions.read_facts(runner)
        if facts.get("model", "").lower() != DISTRIBUTION:
            return None
        return {**facts, "type": PACK_ID}

    def transport_for(self, device: Device, settings: Mapping[str, Any]) -> SshTransport:
        """Open a connected transport to `device`.

        **PARAMETERS:**
            `device` (Device): The target.  <br>
            `settings` (Mapping[str, Any]): The device's resolved `vars.ssh` block. Secrets arrive already resolved.  <br>

        **RETURNS:**
            `SshTransport`: A connected transport. The caller closes it.  <br>
        """
        transport = SshTransport(device.address, SshSettings.from_mapping(settings), use_sudo=self.quirks.use_sudo)
        transport.connect()
        return transport

    def app_manager(self, transport: Transport) -> FlatpakAppManager:
        """RETURNS: FlatpakAppManager: An application manager for this host's Flatpak apps."""
        return FlatpakAppManager(transport)

    def state_manager(self, transport: Transport) -> PosixStateManager:
        """RETURNS: PosixStateManager: A state manager carrying this pack's quirks."""
        return PosixStateManager(transport, self.quirks)

    def state_root(self, transport: Transport, spec: AppStateSpec) -> str:
        """RETURNS: str: Where `spec`'s app keeps its state on this device."""
        return self.state_manager(transport).state_root(spec)

    def check(self, context: DeviceStepContext) -> StepResult:
        """Report what the device says about itself.

        **RETURNS:**
            `StepResult`: Facts gathered, with anything the device declined to answer simply absent.  <br>
        """
        # `/home`, not the staging dir: the latter is `~`-relative and would be
        # passed to `df` quoted, so the shell would not expand it. `/home` is
        # the writable partition a profile actually lands on.
        facts = actions.health(context.transport, storage_path="/home")
        detail = ", ".join(f"{key}={value}" for key, value in sorted(facts.items()))
        context.handle.log(detail or "device answered nothing")
        return StepResult(summary=f"{context.device.id}: {detail or 'no response'}", facts=dict(facts))

    def maintain(self, context: DeviceStepContext) -> StepResult:
        """Reclaim space on the writable partition.

        Device-level only — this pack does not know which applications are
        installed or what their data means.

        **PARAMETERS:**
            `context` (DeviceStepContext): The device, its transport, and resolved config.  <br>

        **RETURNS:**
            `StepResult`: Free space before and after, and what was pruned.  <br>
        """
        runner = context.transport
        recipe = context.config.get("maintenance") or self._data("maintenance")
        before = context.transport.free_bytes("/home")

        paths = [str(path) for path in recipe.get("prune_paths") or []]
        context.handle.log(f"Pruning {len(paths)} path(s)...")
        removed = actions.remove_paths(runner, paths)

        retention = str(recipe.get("journal_retention") or "")
        if retention:
            context.handle.check_cancelled()
            context.handle.log(f"Trimming the journal to {retention}...")
            actions.trim_journal(runner, retention)

        dropped_runtimes = False
        if recipe.get("remove_unused_runtimes"):
            context.handle.check_cancelled()
            context.handle.log("Removing unused Flatpak runtimes...")
            actions.remove_unused_flatpaks(runner)
            dropped_runtimes = True

        after = context.transport.free_bytes("/home")
        reclaimed = max(after - before, 0)
        context.handle.log(f"Reclaimed {reclaimed // (1024 * 1024)}MB")
        return StepResult(
            summary=f"Maintained {context.device.id}: reclaimed {reclaimed // (1024 * 1024)}MB",
            facts={"pruned": removed, "reclaimed_bytes": reclaimed, "free_bytes": after, "runtimes_removed": dropped_runtimes},
        )
