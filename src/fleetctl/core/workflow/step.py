"""What a step is, and what it is allowed to touch."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Protocol

from fleetctl.core.appmgr import AppManager
from fleetctl.core.artifacts.ref import ArtifactRef
from fleetctl.core.artifacts.store import ArtifactStore
from fleetctl.core.effects import Capability, Effect
from fleetctl.core.inventory.device import Device
from fleetctl.core.inventory.store import DeviceStore
from fleetctl.core.operations.registry import OperationHandle
from fleetctl.core.state import StateManager
from fleetctl.core.transport.base import Transport

if TYPE_CHECKING:
    # Runtime import would close the loop step -> scan -> claim -> registry -> step.
    from fleetctl.core.discovery.scan import Scanner


@dataclass(frozen=True, slots=True)
class StepResult:
    """What a step reports back.

    **PARAMETERS:**
        `summary` (str): Human-readable outcome, shown in the timeline.  <br>
        `artifacts` (Mapping[str, ArtifactRef]): Artifacts this step produced, by role, e.g. ``{"build": ref}``.  <br>
        `facts` (Mapping[str, Any]): Values a later step or the caller may want, e.g. a discovered version.  <br>
    """

    summary: str
    artifacts: Mapping[str, ArtifactRef] = field(default_factory=dict)
    facts: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FleetStepContext:
    """What a step with no device target receives.

    **PARAMETERS:**
        `artifacts` (ArtifactStore): Where artifacts are read and written.  <br>
        `inventory` (DeviceStore): The known fleet.  <br>
        `config` (Mapping[str, Any]): Config already resolved for this step.  <br>
        `handle` (OperationHandle): Timeline logging and cancellation.  <br>
        `workspace` (Path): Staging directory for this operation.  <br>
    """

    artifacts: ArtifactStore
    inventory: DeviceStore
    config: Mapping[str, Any]
    handle: OperationHandle
    workspace: Path


@dataclass(frozen=True, slots=True)
class DeviceStepContext:
    """What a step targeting one device receives.

    **PARAMETERS:**
        `device` (Device): The target. Never optional here.  <br>
        `transport` (Transport): Already wrapped for auditing by the composition root.  <br>
        `state` (StateManager): The device pack's state manager for this device.  <br>
        `apps` (AppManager): The device pack's application manager for this device.  <br>
        `artifacts` (ArtifactStore): Where artifacts are read and written.  <br>
        `inventory` (DeviceStore): The known fleet.  <br>
        `config` (Mapping[str, Any]): Config already resolved for this device and step.  <br>
        `handle` (OperationHandle): Timeline logging and cancellation.  <br>
        `workspace` (Path): Staging directory for this operation.  <br>
    """

    device: Device
    transport: Transport
    state: StateManager
    apps: AppManager
    artifacts: ArtifactStore
    inventory: DeviceStore
    config: Mapping[str, Any]
    handle: OperationHandle
    workspace: Path


@dataclass(frozen=True, slots=True)
class DiscoveryStepContext:
    """What a step that looks for devices receives.

    Carries no transport: discovery decides what to open a transport to, so
    it cannot be handed one.

    **PARAMETERS:**
        `scanner` (Scanner): Sweeps, identifies, and records what it finds.  <br>
        `config` (Mapping[str, Any]): Config resolved for this step.  <br>
        `handle` (OperationHandle): Timeline logging and cancellation.  <br>
        `workspace` (Path): Staging directory for this operation.  <br>
    """

    scanner: Scanner
    config: Mapping[str, Any]
    handle: OperationHandle
    workspace: Path


class ProfileTransform(Protocol):
    """A pure change applied to an extracted profile directory."""

    @property
    def name(self) -> str:
        """RETURNS: str: Short identifier for logs and audit records."""

    def apply(self, profile: Path, config: Mapping[str, Any]) -> list[str]:
        """Mutate `profile` in place and describe what changed.

        **PARAMETERS:**
            `profile` (Path): Extracted profile directory.  <br>
            `config` (Mapping[str, Any]): Resolved configuration for this transform.  <br>

        **RETURNS:**
            `list[str]`: Human-readable descriptions of each change made.  <br>
        """


@dataclass(frozen=True, slots=True)
class TransformStepContext:
    """What a build-style step receives: transforms, and deliberately no transport.

    **PARAMETERS:**
        `transforms` (tuple[ProfileTransform, ...]): The chain to apply, in order.  <br>
        `artifacts` (ArtifactStore): Where artifacts are read and written.  <br>
        `config` (Mapping[str, Any]): Config already resolved for this step.  <br>
        `handle` (OperationHandle): Timeline logging and cancellation.  <br>
        `workspace` (Path): Staging directory for this operation.  <br>
    """

    transforms: tuple[ProfileTransform, ...]
    artifacts: ArtifactStore
    config: Mapping[str, Any]
    handle: OperationHandle
    workspace: Path


@dataclass(frozen=True, slots=True)
class StepSpec:
    """Everything the engine and every port adapter need to know about a step.

    **PARAMETERS:**
        `id` (str): Dotted identifier, e.g. ``kodi.deploy``.  <br>
        `summary` (str): One-line description, surfaced to users and agents.  <br>
        `effect` (Effect): How much this step changes. Drives policy and audit.  <br>
        `requires` (frozenset[Capability]): Capabilities the target must provide, checked at plan time.  <br>
        `scope` (str): One of ``device``, ``fleet``, or ``transform``, selecting which context this step receives.  <br>
    """

    id: str
    summary: str
    effect: Effect = Effect.MUTATING
    requires: frozenset[Capability] = frozenset()
    scope: str = "device"
