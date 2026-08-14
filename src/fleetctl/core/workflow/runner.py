"""Running one step: the common envelope every step gets."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Mapping

from fleetctl.core.effects import WIRE_CAPABILITIES, Capability, missing_capabilities
from fleetctl.core.errors import FleetError, OperationCancelled
from fleetctl.core.observability.correlation import correlate
from fleetctl.core.operations.registry import OperationHandle, OperationRegistry, OperationStatus
from fleetctl.core.operations.workspace import workspace
from fleetctl.core.transport.base import Transport
from fleetctl.core.workflow.step import StepResult, StepSpec

LOGGER = logging.getLogger(__name__)

StepBody = Callable[[OperationHandle, Path], StepResult]


def check_capabilities(spec: StepSpec, transport: Transport, *, provided_by_pack: frozenset[Capability] = frozenset()) -> None:
    """Verify a target can satisfy a step before anything is touched.

    A transport carries the wire verbs — reach, exec, files. The deeper ones
    are supplied by the pack's own managers: `state` and `apps` are built on
    exec and files, and whether a pack has them is a property of the pack, not
    of the connection. One `SshTransport` serves both a Steam Deck, which has a
    state manager, and a generic Linux host, which does not, so the transport
    cannot answer for either. Checking it alone rejected steps the pack could
    in fact run.

    **PARAMETERS:**
        `spec` (StepSpec): The step about to run.  <br>
        `transport` (Transport): The resolved transport for the target.  <br>
        `provided_by_pack` (frozenset[Capability]): What the device pack declares. Defaults to empty, leaving the transport the sole authority — correct when there is no pack, as in a direct transport test.  <br>

    **RAISES:**
        `FleetError`: If neither the transport nor the pack provides something the step requires.  <br>
    """
    # A pack may add the derived verbs it implements, but never claim a wire
    # verb the connection does not have — that would hide a dead transport
    # behind a pack's declaration.
    provided = transport.capabilities() | (provided_by_pack - WIRE_CAPABILITIES)
    missing = missing_capabilities(spec.requires, provided)
    if missing:
        names = ", ".join(sorted(capability.value for capability in missing))
        raise FleetError(f"{spec.id} requires unsupported capabilities on {transport.target}: {names}")


def run_step(
    registry: OperationRegistry,
    spec: StepSpec,
    body: StepBody,
    *,
    op_id: str,
    target: str = "",
    actor: str = "-",
    run_id: str = "-",
    params: Mapping[str, Any] | None = None,
    staging_root: Path,
    failures_root: Path | None = None,
) -> OperationStatus:
    """Run one step body inside the standard envelope.

    **PARAMETERS:**
        `registry` (OperationRegistry): Where the operation is tracked.  <br>
        `spec` (StepSpec): The step being run.  <br>
        `body` (StepBody): The work itself, as ``(handle, workspace) -> StepResult``.  <br>
        `op_id` (str): Unique operation id.  <br>
        `target` (str): Device id or address, empty for fleet-level work.  <br>
        `actor` (str): Who initiated this, recorded on every audit event.  <br>
        `run_id` (str): Correlation id for the enclosing workflow run.  <br>
        `params` (Mapping[str, Any] | None): Flags this run was given, recorded on the operation so it can be rerun.  <br>
        `staging_root` (Path): Parent directory for the operation's workspace.  <br>
        `failures_root` (Path | None, optional): Where to preserve the workspace on failure. Defaults to ``None``.  <br>

    **RETURNS:**
        `OperationStatus`: The terminal status recorded for this operation.  <br>

    **RAISES:**
        `FleetError`: If another operation is already running against `target`.  <br>
    """
    # Two jobs on one device interleave their extracts and leave a profile
    # that is neither. Fleet-scoped work has no target and does not contend.
    busy = registry.running_for(target) if target else None
    if busy is not None and busy != op_id:
        raise FleetError(f"{target} is busy with {busy}; wait for it or cancel it before starting {spec.id}")

    handle = registry.start(op_id, spec.id, target, params)
    with correlate(run_id=run_id, step_id=spec.id, op_id=op_id, actor=actor):
        try:
            with workspace(staging_root, op_id, failures_root=failures_root) as staging:
                result = body(handle, staging)
            handle.complete(result.summary, result.facts)
            return OperationStatus.COMPLETED
        except OperationCancelled:
            handle.cancelled()
            return OperationStatus.CANCELLED
        except Exception as exc:  # noqa: BLE001 - recorded on the operation, never swallowed silently
            LOGGER.exception("Step %s failed for %s", spec.id, target or "fleet")
            handle.fail(str(exc))
            return OperationStatus.FAILED
