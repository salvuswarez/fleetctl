"""The Fire TV pack: probe, capabilities, and the maintain step."""

from __future__ import annotations

import logging
from functools import cached_property
from importlib import resources
from pathlib import Path
from typing import Any, Mapping

import yaml

from ...core.effects import Capability, Effect
from ...core.inventory.device import Device
from ...core.registry import RegisteredStep
from ...core.state import AppStateSpec
from ...core.transport.base import CommandRunner, Transport
from ...core.workflow.step import DeviceStepContext, StepResult, StepSpec
from ..android import actions
from ..android.appmgr import AndroidAppManager
from ..android.keys import AdbKeyStore
from ..android.quirks import AndroidQuirks
from ..android.state import AndroidStateManager
from ..android.transport import AdbTransport

LOGGER = logging.getLogger(__name__)

PACK_ID = "firetv"
PLATFORM = "android"
MANUFACTURER = "Amazon"

CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.REACH,
        Capability.FACTS,
        Capability.EXEC,
        Capability.FILES,
        Capability.APPS,
        Capability.SETTINGS,
        Capability.POWER,
        Capability.STATE,
        Capability.CLEANUP,
    }
)

MAINTAIN = StepSpec(
    id="firetv.maintain",
    summary="Disable Amazon bloatware, apply performance settings, and trim caches.",
    effect=Effect.DESTRUCTIVE,
    requires=frozenset({Capability.EXEC, Capability.APPS, Capability.SETTINGS, Capability.CLEANUP}),
    scope="device",
)


CHECK = StepSpec(
    id="firetv.check",
    summary="Report a Fire TV device's identity, uptime and free space.",
    effect=Effect.READ,
    requires=frozenset({Capability.EXEC, Capability.FACTS}),
    scope="device",
)


def _load(name: str) -> dict[str, Any]:
    """RETURNS: dict[str, Any]: A parsed data file shipped with this pack."""
    text = resources.files(f"fleetctl.packs.{PACK_ID}.data").joinpath(name).read_text(encoding="utf-8")
    loaded = yaml.safe_load(text)
    return loaded if isinstance(loaded, dict) else {}


class FireTvPack:
    """Fire TV Stick support.

    **PARAMETERS:**
        `data` (Mapping[str, Any] | None): Overrides for the pack's shipped data files, keyed by file stem. Defaults to ``None``, meaning use what ships.  <br>
    """

    id = PACK_ID
    platform = PLATFORM
    capabilities = CAPABILITIES
    probe_priority = 10

    def __init__(self, data: Mapping[str, Any] | None = None) -> None:
        self._overrides = dict(data or {})

    @cached_property
    def quirks(self) -> AndroidQuirks:
        """RETURNS: AndroidQuirks: Fire OS deviations, from `data/quirks.yml`."""
        return AndroidQuirks.from_mapping(self._data("quirks"))

    @cached_property
    def bloat_packages(self) -> tuple[str, ...]:
        """RETURNS: tuple[str, ...]: Every package listed in `data/bloat.yml`, across all categories."""
        grouped = self._data("bloat")
        return tuple(package for group in grouped.values() if isinstance(group, list) for package in group)

    def _data(self, name: str) -> dict[str, Any]:
        override = self._overrides.get(name)
        if isinstance(override, dict):
            return override
        return _load(f"{name}.yml")

    def steps(self) -> list[RegisteredStep]:
        """RETURNS: list[RegisteredStep]: The steps this pack provides."""
        return [
            RegisteredStep(spec=MAINTAIN, run=self.maintain, provider=PACK_ID),
            RegisteredStep(spec=CHECK, run=self.check, provider=PACK_ID),
        ]

    def probe(self, runner: CommandRunner) -> dict[str, str] | None:
        """Claim a host if it is an Amazon device.

        **PARAMETERS:**
            `runner` (CommandRunner): Connection to the candidate host.  <br>

        **RETURNS:**
            `dict[str, str] | None`: Device facts if this pack claims the host, otherwise ``None``. A subnet sweep hits mostly non-devices, so an unrecognized host is a normal outcome, never an error.  <br>
        """
        facts = actions.read_facts(runner)
        if not facts.get("model"):
            return None
        if MANUFACTURER.lower() not in facts.get("manufacturer", "").lower():
            return None
        return {**facts, "type": PACK_ID}

    def transport_for(self, device: Device, settings: Mapping[str, Any]) -> AdbTransport:
        """Open a connected transport to `device`.

        **PARAMETERS:**
            `device` (Device): The target.  <br>
            `settings` (Mapping[str, Any]): Must carry `key_dir`, the directory holding ADB key material.  <br>

        **RETURNS:**
            `AdbTransport`: A connected transport. The caller closes it.  <br>
        """
        keys = AdbKeyStore(Path(str(settings["key_dir"])), settings.get("audit"))
        transport = AdbTransport(device.address, keys, use_netcat=self.quirks.push_via_netcat)
        transport.connect()
        return transport

    def app_manager(self, transport: Transport) -> AndroidAppManager:
        """RETURNS: AndroidAppManager: An application manager carrying this pack's quirks."""
        return AndroidAppManager(transport, self.quirks)

    def state_manager(self, transport: Transport) -> AndroidStateManager:
        """RETURNS: AndroidStateManager: A state manager carrying this pack's quirks."""
        return AndroidStateManager(transport, self.quirks)

    def state_root(self, transport: Transport, spec: AppStateSpec) -> str:
        """RETURNS: str: Where `spec`'s app keeps its state on this device."""
        return self.state_manager(transport).state_root(spec)

    def check(self, context: DeviceStepContext) -> StepResult:
        """Report what the device says about itself.

        **RETURNS:**
            `StepResult`: Facts gathered, with anything the device declined to answer simply absent.  <br>
        """
        facts = actions.health(context.transport, storage_path=self.quirks.external_storage)
        detail = ", ".join(f"{key}={value}" for key, value in sorted(facts.items()))
        context.handle.log(detail or "device answered nothing")
        return StepResult(summary=f"{context.device.id}: {detail or 'no response'}", facts=dict(facts))

    def maintain(self, context: DeviceStepContext) -> StepResult:
        """Disable bloatware, apply performance settings, and trim caches.

        **PARAMETERS:**
            `context` (DeviceStepContext): The device, its transport, and resolved config.  <br>

        **RETURNS:**
            `StepResult`: A summary plus `facts` carrying which packages actually got disabled.  <br>
        """
        runner = context.transport
        maintenance = self._data("maintenance")
        packages = tuple(context.config.get("bloat_packages") or self.bloat_packages)

        context.handle.log(f"Disabling {len(packages)} packages...")
        context.handle.check_cancelled()
        outcomes = actions.disable_packages(runner, packages, self.quirks)
        blocked = [outcome.package for outcome in outcomes if not outcome.disabled]
        if blocked:
            context.handle.log(f"{len(blocked)} package(s) could not be disabled (Fire OS restriction): {', '.join(sorted(blocked)[:5])}")

        context.handle.check_cancelled()
        context.handle.log("Applying performance and telemetry settings...")
        for change in actions.apply_settings(runner, maintenance.get("settings", {})):
            context.handle.log(f"  {change}")

        context.handle.check_cancelled()
        context.handle.log("Trimming caches...")
        actions.trim_caches(runner, str(maintenance.get("cache_reserve", "16G")))
        actions.remove_paths(runner, maintenance.get("prune_paths", []))

        disabled = len(outcomes) - len(blocked)
        return StepResult(
            summary=f"Maintained {context.device.id}: {disabled}/{len(outcomes)} packages disabled",
            facts={"disabled": disabled, "blocked": blocked, "verified": self.quirks.verify_disable_user},
        )
