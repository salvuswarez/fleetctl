"""What a step is, and what it is allowed to touch."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol

from ..appmgr import AppManager
from ..artifacts.ref import ArtifactRef
from ..artifacts.store import ArtifactStore
from ..effects import Capability, Effect
from ..inventory.device import Device
from ..inventory.store import DeviceStore
from ..operations.registry import OperationHandle
from ..state import StateManager
from ..transport.base import Transport


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
