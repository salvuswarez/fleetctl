"""The Linux host pack: probe, capabilities, and a read-only health check."""

from __future__ import annotations

import logging
from functools import cached_property
from importlib import resources
from typing import Any, Mapping

import yaml

from ...core.effects import Capability, Effect
from ...core.inventory.device import Device
from ...core.registry import RegisteredStep
from ...core.transport.base import CommandRunner
from ...core.workflow.step import DeviceStepContext, StepResult, StepSpec
from ..posix import actions
from ..posix.quirks import PosixQuirks
from ..posix.transport import SshSettings, SshTransport

LOGGER = logging.getLogger(__name__)

PACK_ID = "linux_host"
PLATFORM = "linux"

# Distribution ids this pack declines, because a pack that knows their quirks
# should claim them instead. Claiming a SteamOS box as a generic Linux host
# would hand it a writable-root assumption that is false there.
DECLINED_DISTRIBUTIONS: frozenset[str] = frozenset({"steamos"})

# No STATE: resolving where an application keeps its data is what the `state`
# verb promises, and on Linux that answer differs between a native install and
# a Flatpak sandbox. Declaring it before that is settled on hardware would let
# `kodi.deploy` plan successfully and then write to the wrong directory.
#
# No APPS or SETTINGS: package management is distribution-specific and this
# pack ships no verified package list.
CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.REACH,
        Capability.FACTS,
        Capability.EXEC,
        Capability.FILES,
        Capability.POWER,
        Capability.CLEANUP,
    }
)

CHECK = StepSpec(
    id="linux_host.check",
    summary="Report a Linux host's identity, uptime and free space.",
    effect=Effect.READ,
    requires=frozenset({Capability.EXEC, Capability.FACTS}),
    scope="device",
)


def _load(name: str) -> dict[str, Any]:
    """RETURNS: dict[str, Any]: A parsed data file shipped with this pack."""
    text = resources.files(f"fleetctl.packs.{PACK_ID}.data").joinpath(name).read_text(encoding="utf-8")
    loaded = yaml.safe_load(text)
    return loaded if isinstance(loaded, dict) else {}


class LinuxHostPack:
    """Generic Linux host support over SSH.

    **PARAMETERS:**
        `data` (Mapping[str, Any] | None): Overrides for the shipped data files, keyed by file stem. Defaults to ``None``, meaning use what ships.  <br>
    """

    id = PACK_ID
    platform = PLATFORM
    capabilities = CAPABILITIES
    # Probes last: the Android packs key off `getprop`, which a Linux host
    # does not answer, but a vendor-specific Linux pack must get first refusal
    # on the hosts it knows.
    probe_priority = 50
    app_profiles: Mapping[str, str] = {}

    def __init__(self, data: Mapping[str, Any] | None = None) -> None:
        self._overrides = dict(data or {})

    @cached_property
    def quirks(self) -> PosixQuirks:
        """RETURNS: PosixQuirks: Host deviations, from `data/quirks.yml`. Currently all conventional-Linux defaults."""
        return PosixQuirks.from_mapping(self._data("quirks"))

    def _data(self, name: str) -> dict[str, Any]:
        override = self._overrides.get(name)
        if isinstance(override, dict):
            return override
        return _load(f"{name}.yml")

    def steps(self) -> list[RegisteredStep]:
        """RETURNS: list[RegisteredStep]: The steps this pack provides."""
        return [RegisteredStep(spec=CHECK, run=self.check, provider=PACK_ID)]

    def probe(self, runner: CommandRunner) -> dict[str, str] | None:
        """Claim a host if it answers as a Linux system this pack should manage.

        **PARAMETERS:**
            `runner` (CommandRunner): Connection to the candidate host.  <br>

        **RETURNS:**
            `dict[str, str] | None`: Device facts if this pack claims the host, otherwise ``None``. A subnet sweep hits mostly non-devices, so an unrecognized host is a normal outcome, never an error.  <br>
        """
        facts = actions.read_facts(runner)
        # `model` carries the os-release ID. Without it the host is not
        # answering as Linux at all, so return nothing rather than a
        # partially-filled identity.
        distribution = facts.get("model", "")
        if not distribution:
            return None
        if distribution.lower() in DECLINED_DISTRIBUTIONS:
            return None
        return {**facts, "type": PACK_ID}

    def transport_for(self, device: Device, settings: Mapping[str, Any]) -> SshTransport:
        """Open a connected transport to `device`.

        **PARAMETERS:**
            `device` (Device): The target.  <br>
            `settings` (Mapping[str, Any]): The device's resolved `vars.ssh` block — `user`, and one of `key_path` or `password`. Secrets arrive already resolved.  <br>

        **RETURNS:**
            `SshTransport`: A connected transport. The caller closes it.  <br>
        """
        transport = SshTransport(device.address, SshSettings.from_mapping(settings), use_sudo=self.quirks.use_sudo)
        transport.connect()
        return transport

    def check(self, context: DeviceStepContext) -> StepResult:
        """Report what the host says about itself.

        **RETURNS:**
            `StepResult`: Facts gathered, with anything the host declined to answer simply absent.  <br>
        """
        facts = actions.health(context.transport, storage_path=self.quirks.staging_dir)
        detail = ", ".join(f"{key}={value}" for key, value in sorted(facts.items()))
        context.handle.log(detail or "host answered nothing")
        return StepResult(summary=f"{context.device.id}: {detail or 'no response'}", facts=dict(facts))
