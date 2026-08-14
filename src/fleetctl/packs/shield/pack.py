"""The Shield pack: probe, capabilities, and maintenance."""

from __future__ import annotations

import logging
from functools import cached_property
from importlib import resources
from pathlib import Path
from typing import Any, Mapping

import yaml

from fleetctl.core.effects import Capability, Effect
from fleetctl.core.inventory.device import Device
from fleetctl.core.registry import RegisteredStep
from fleetctl.core.state import AppStateSpec
from fleetctl.core.transport.base import CommandRunner, Transport
from fleetctl.core.workflow.step import DeviceStepContext, StepResult, StepSpec
from fleetctl.packs.android import actions, devicesteps
from fleetctl.packs.android.appmgr import AndroidAppManager
from fleetctl.packs.android.devicestate import AndroidDeviceStateManager, DeviceStatePolicy
from fleetctl.packs.android.keys import AdbKeyStore
from fleetctl.packs.android.quirks import AndroidQuirks
from fleetctl.packs.android.state import AndroidStateManager
from fleetctl.packs.android.transport import AdbTransport

LOGGER = logging.getLogger(__name__)

PACK_ID = "shield"
PLATFORM = "android"
MANUFACTURER = "NVIDIA"

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
    id="shield.maintain",
    summary="Disable configured packages and trim caches on an NVIDIA Shield.",
    effect=Effect.DESTRUCTIVE,
    requires=frozenset({Capability.EXEC, Capability.APPS, Capability.CLEANUP}),
    scope="device",
)


CHECK = StepSpec(
    id="shield.check",
    summary="Report a Shield device's identity, uptime and free space.",
    effect=Effect.READ,
    requires=frozenset({Capability.EXEC, Capability.FACTS}),
    scope="device",
)

# What the device *is*, as opposed to what an app on it keeps — its settings,
# its packages, and the APKs to put them back. Shared with every Android pack:
# `settings` and `pm` are the platform's, not NVIDIA's.
CAPTURE_STATE = devicesteps.capture_spec(PACK_ID)
RESTORE_STATE = devicesteps.restore_spec(PACK_ID)


def _load(name: str) -> dict[str, Any]:
    """RETURNS: dict[str, Any]: A parsed data file shipped with this pack."""
    text = resources.files(f"fleetctl.packs.{PACK_ID}.data").joinpath(name).read_text(encoding="utf-8")
    loaded = yaml.safe_load(text)
    return loaded if isinstance(loaded, dict) else {}


class ShieldPack:
    """NVIDIA Shield support.

    **PARAMETERS:**
        `data` (Mapping[str, Any] | None): Overrides for the shipped data files, keyed by file stem. Defaults to ``None``.  <br>
    """

    id = PACK_ID
    platform = PLATFORM
    capabilities = CAPABILITIES
    # Probes ahead of nothing in particular; both vendor packs key off
    # manufacturer, so neither can claim the other's device.
    probe_priority = 10
    # The gold recipe is shaped by a 1.7GB stick: a small file cache and no
    # home-screen preloading. This device has 2.88GB, so it takes a recipe
    # that lifts those limits. Same addons and skin — only the constraints
    # differ. See `data/profiles/shield.yml`.
    app_profiles: Mapping[str, str] = {"kodi": "shield"}

    def __init__(self, data: Mapping[str, Any] | None = None) -> None:
        self._overrides = dict(data or {})

    @cached_property
    def quirks(self) -> AndroidQuirks:
        """RETURNS: AndroidQuirks: Shield deviations. Currently none beyond stock Android."""
        return AndroidQuirks.from_mapping(self._data("quirks"))

    @cached_property
    def bloat_packages(self) -> tuple[str, ...]:
        """RETURNS: tuple[str, ...]: Packages listed in `data/bloat.yml`. Empty until verified on hardware."""
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
            RegisteredStep(spec=CAPTURE_STATE, run=self.capture_state, provider=PACK_ID),
            RegisteredStep(spec=RESTORE_STATE, run=self.restore_state, provider=PACK_ID),
        ]

    def probe(self, runner: CommandRunner) -> dict[str, str] | None:
        """Claim a host if it is an NVIDIA device.

        **RETURNS:**
            `dict[str, str] | None`: Device facts if claimed, otherwise ``None``.  <br>
        """
        facts = actions.read_facts(runner)
        if not facts.get("model"):
            return None
        if MANUFACTURER.lower() not in facts.get("manufacturer", "").lower():
            return None
        return {**facts, "type": PACK_ID}

    def transport_for(self, device: Device, settings: Mapping[str, Any]) -> AdbTransport:
        """RETURNS: AdbTransport: A connected transport, using this pack's own quirks."""
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

    @cached_property
    def device_state_policy(self) -> DeviceStatePolicy:
        """RETURNS: DeviceStatePolicy: What a snapshot of this device may carry and replay. Overridable per pack, though nothing here is vendor-specific yet."""
        override = self._overrides.get("device_state")
        return DeviceStatePolicy.from_mapping(override) if isinstance(override, dict) else DeviceStatePolicy.shipped()

    def device_state_manager(self, transport: Transport) -> AndroidDeviceStateManager:
        """RETURNS: AndroidDeviceStateManager: A device-state manager carrying this pack's quirks and policy."""
        return AndroidDeviceStateManager(transport, self.quirks, self.device_state_policy)

    def power_state(self, transport: Transport) -> str:
        """RETURNS: str: ``awake``/``asleep``/``dozing``/``dreaming``, or ``""`` when unreadable. Satisfies the `power` capability this pack declares."""
        return actions.power_state(transport)

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

    def capture_state(self, context: DeviceStepContext) -> StepResult:
        """Capture this device's settings, packages and APKs.

        **RETURNS:**
            `StepResult`: Carries the published snapshot under the ``device_state`` artifact role.  <br>
        """
        return devicesteps.capture_state(self.device_state_manager(context.transport), context)

    def restore_state(self, context: DeviceStepContext) -> StepResult:
        """Rewrite this device's settings and reinstall its packages from a snapshot.

        **RETURNS:**
            `StepResult`: What was applied, skipped and refused.  <br>
        """
        return devicesteps.restore_state(self.device_state_manager(context.transport), context)

    def maintain(self, context: DeviceStepContext) -> StepResult:
        """Disable configured packages and trim caches.

        **RETURNS:**
            `StepResult`: A summary plus per-package outcomes.  <br>
        """
        packages = tuple(context.config.get("bloat_packages") or self.bloat_packages)
        if not packages:
            context.handle.log("No packages configured for this pack; nothing to disable.")
            return StepResult(summary=f"{context.device.id}: nothing configured to disable", facts={"disabled": 0, "blocked": []})

        context.handle.log(f"Disabling {len(packages)} packages...")
        context.handle.check_cancelled()
        outcomes = actions.disable_packages(context.transport, packages, self.quirks)
        blocked = [outcome.package for outcome in outcomes if not outcome.disabled]

        context.handle.check_cancelled()
        context.handle.log("Trimming caches...")
        actions.trim_caches(context.transport)

        disabled = len(outcomes) - len(blocked)
        return StepResult(
            summary=f"Maintained {context.device.id}: {disabled}/{len(outcomes)} packages disabled",
            facts={"disabled": disabled, "blocked": blocked, "verified": self.quirks.verify_disable_user},
        )
