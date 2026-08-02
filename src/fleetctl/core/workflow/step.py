"""What a step is, and what it is allowed to touch.

Three context types rather than one, because there are three kinds of step
and a single context made two claims false:

- A fleet-level step (build an artifact, fetch a base image) has no device,
  so a shared context had to type `device` as optional and hand it a
  transport it must never use.
- The guarantee that "transforms cannot live in deploy" was enforced only by
  discipline. Here it is structural: `TransformStepContext` carries a
  transform chain and no transport, `DeviceStepContext` carries a transport
  and no transform chain. A deploy step has nothing to transform *with*.

None of them carry an audit sink, logger, or redactor. The transport arrives
already wrapped and correlation rides a context variable, so auditing is a
property of the wiring rather than something an author must remember.
"""

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

    A bare summary string cannot carry an artifact forward to a later step,
    which is what the predecessor's `-> str` return type made impossible.

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

    `state` is the resolved device pack's implementation of the `state` verb.
    Handing it to the step here — rather than having the step ask for it —
    is what lets an app pack snapshot and restore without ever learning which
    pack it is talking to. It is guaranteed present for any step declaring
    `Capability.STATE`, because the engine checks capabilities before running.

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

    One registration yields a CLI command, a Home Assistant service schema,
    and an MCP tool — none of which are written by hand.

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
