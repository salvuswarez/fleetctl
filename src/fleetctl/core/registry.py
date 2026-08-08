"""Plugin discovery: what packs exist, and what steps they offer."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Callable, Iterable, Mapping, Protocol, runtime_checkable

from .effects import Capability
from .errors import FleetError
from .transport.base import CommandRunner
from .workflow.step import StepResult, StepSpec

LOGGER = logging.getLogger(__name__)

PACK_GROUP = "fleetctl.packs"
APP_GROUP = "fleetctl.apps"

StepBody = Callable[[Any], StepResult]


@dataclass(frozen=True, slots=True)
class RegisteredStep:
    """A step, and who provides it.

    **PARAMETERS:**
        `spec` (StepSpec): Identity, effect class, and required capabilities.  <br>
        `run` (StepBody): The body, taking whichever context `spec.scope` selects.  <br>
        `provider` (str): Id of the pack or app that registered it.  <br>
    """

    spec: StepSpec
    run: StepBody
    provider: str


@runtime_checkable
class DevicePack(Protocol):
    """What a device pack must expose to be usable."""

    id: str
    platform: str
    capabilities: frozenset[Capability]
    probe_priority: int

    @property
    def app_profiles(self) -> Mapping[str, str]:
        """RETURNS: Mapping[str, str]: App id -> the profile this hardware needs, for apps shipping more than one. Empty means every app's default is right.

        The pack states this because the hardware is the reason: a build shaped
        for a Fire Stick carries ARM addon binaries a Steam Deck cannot execute,
        and nothing else in the chain knows that. Read at the composition root;
        an app pack never sees it.
        """

    def probe(self, runner: CommandRunner) -> dict[str, str] | None:
        """RETURNS: dict[str, str] | None: Device facts if this pack claims the host, else None."""

    def steps(self) -> Iterable[RegisteredStep]:
        """RETURNS: Iterable[RegisteredStep]: Steps this pack provides."""


@runtime_checkable
class AppPack(Protocol):
    """What an app pack must expose to be usable."""

    id: str

    def steps(self) -> Iterable[RegisteredStep]:
        """RETURNS: Iterable[RegisteredStep]: Steps this app provides."""


class Registry:
    """Everything discovered: device packs, app packs, and their steps."""

    def __init__(self) -> None:
        self._device_packs: dict[str, DevicePack] = {}
        self._app_packs: dict[str, AppPack] = {}
        self._steps: dict[str, RegisteredStep] = {}

    def register_device_pack(self, pack: DevicePack) -> None:
        """Register a device pack and its steps.

        **RAISES:**
            `FleetError`: If a pack or step id is already taken. A silent overwrite would let one pack shadow another's steps.  <br>
        """
        if pack.id in self._device_packs:
            raise FleetError(f"Device pack {pack.id!r} is already registered")
        self._device_packs[pack.id] = pack
        self._add_steps(pack.steps())

    def register_app_pack(self, pack: AppPack) -> None:
        """Register an app pack and its steps.

        **RAISES:**
            `FleetError`: If a pack or step id is already taken.  <br>
        """
        if pack.id in self._app_packs:
            raise FleetError(f"App pack {pack.id!r} is already registered")
        self._app_packs[pack.id] = pack
        self._add_steps(pack.steps())

    def register_steps(self, steps: Iterable[RegisteredStep]) -> None:
        """Register steps that belong to no pack, such as discovery.

        **RAISES:**
            `FleetError`: If a step id is already taken.  <br>
        """
        self._add_steps(steps)

    def has_step(self, step_id: str) -> bool:
        """RETURNS: bool: Whether `step_id` is registered."""
        return step_id in self._steps

    def _add_steps(self, steps: Iterable[RegisteredStep]) -> None:
        for step in steps:
            existing = self._steps.get(step.spec.id)
            if existing is not None:
                raise FleetError(f"Step {step.spec.id!r} is already provided by {existing.provider!r}")
            self._steps[step.spec.id] = step

    def device_pack(self, pack_id: str) -> DevicePack:
        """RETURNS: DevicePack: The pack with this id.

        **RAISES:**
            `FleetError`: If no such pack is registered — usually a device whose `type` names a pack that is not installed.  <br>
        """
        pack = self._device_packs.get(pack_id)
        if pack is None:
            known = ", ".join(sorted(self._device_packs)) or "none"
            raise FleetError(f"No device pack {pack_id!r} is registered (known: {known})")
        return pack

    def device_packs(self) -> list[DevicePack]:
        """RETURNS: list[DevicePack]: Every device pack, in probe order — lowest `probe_priority` first."""
        return sorted(self._device_packs.values(), key=lambda pack: (pack.probe_priority, pack.id))

    def app_pack(self, app_id: str) -> AppPack:
        """RETURNS: AppPack: The app pack with this id.

        **RAISES:**
            `FleetError`: If no such app pack is registered.  <br>
        """
        pack = self._app_packs.get(app_id)
        if pack is None:
            raise FleetError(f"No app pack {app_id!r} is registered")
        return pack

    def app_packs(self) -> list[AppPack]:
        """RETURNS: list[AppPack]: Every app pack, sorted by id."""
        return [self._app_packs[app_id] for app_id in sorted(self._app_packs)]

    def step(self, step_id: str) -> RegisteredStep:
        """RETURNS: RegisteredStep: The step with this id.

        **RAISES:**
            `FleetError`: If no such step is registered.  <br>
        """
        step = self._steps.get(step_id)
        if step is None:
            known = ", ".join(sorted(self._steps)) or "none"
            raise FleetError(f"No step {step_id!r} is registered (known: {known})")
        return step

    def steps(self) -> list[RegisteredStep]:
        """RETURNS: list[RegisteredStep]: Every registered step, sorted by id."""
        return [self._steps[step_id] for step_id in sorted(self._steps)]


def discover(registry: Registry | None = None) -> Registry:
    """Load every pack advertised through entry points.

    **PARAMETERS:**
        `registry` (Registry | None): Registry to populate. Defaults to a fresh one.  <br>

    **RETURNS:**
        `Registry`: The populated registry. Packs that fail to import or register are logged and skipped, never raised — one broken third-party pack must not stop the rest of the fleet being managed.  <br>
    """
    registry = registry or Registry()
    _load_group(PACK_GROUP, registry.register_device_pack)
    _load_group(APP_GROUP, registry.register_app_pack)
    return registry


def _load_group(group: str, register: Callable[[Any], None]) -> None:
    for entry in metadata.entry_points(group=group):
        try:
            register(entry.load()())
        except Exception as exc:  # noqa: BLE001 - isolation is the point
            LOGGER.warning("Skipping %s pack %r: %s", group, entry.name, exc)
