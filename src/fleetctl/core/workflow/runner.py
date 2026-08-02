"""Running one step: the common envelope every step gets.

Collapses what the predecessor duplicated across five job bodies — and got
subtly wrong in four of them, which had no `finally` cleanup. Every step gets
its own workspace, correlation ids bound for its whole execution, a uniform
cancelled/failed/completed outcome, and a preserved workspace when it fails.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from ..effects import missing_capabilities
from ..errors import FleetError, OperationCancelled
from ..observability.correlation import correlate
from ..operations.registry import OperationHandle, OperationRegistry, OperationStatus
from ..operations.workspace import workspace
from ..transport.base import Transport
from .step import StepResult, StepSpec

LOGGER = logging.getLogger(__name__)

StepBody = Callable[[OperationHandle, Path], StepResult]


def check_capabilities(spec: StepSpec, transport: Transport) -> None:
    """Verify a transport can satisfy a step before anything is touched.

    Called at plan time so an unsupported step is reported up front rather
    than failing partway through against real hardware.

    **PARAMETERS:**
        `spec` (StepSpec): The step about to run.  <br>
        `transport` (Transport): The resolved transport for the target.  <br>

    **RAISES:**
        `FleetError`: If the transport does not provide everything the step requires.  <br>
    """
    missing = missing_capabilities(spec.requires, transport.capabilities())
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
    staging_root: Path,
    failures_root: Path | None = None,
) -> OperationStatus:
    """Run one step body inside the standard envelope.

    Synchronous and blocking: submit it to an executor to run steps
    concurrently. Exceptions are recorded and not re-raised, so one failing
    device cannot abort a fleet-wide run.

    **PARAMETERS:**
        `registry` (OperationRegistry): Where the operation is tracked.  <br>
        `spec` (StepSpec): The step being run.  <br>
        `body` (StepBody): The work itself, as ``(handle, workspace) -> StepResult``.  <br>
        `op_id` (str): Unique operation id.  <br>
        `target` (str): Device id or address, empty for fleet-level work.  <br>
        `actor` (str): Who initiated this, recorded on every audit event.  <br>
        `run_id` (str): Correlation id for the enclosing workflow run.  <br>
        `staging_root` (Path): Parent directory for the operation's workspace.  <br>
        `failures_root` (Path | None, optional): Where to preserve the workspace on failure. Defaults to ``None``.  <br>

    **RETURNS:**
        `OperationStatus`: The terminal status recorded for this operation.  <br>
    """
    handle = registry.start(op_id, spec.id, target)
    with correlate(run_id=run_id, step_id=spec.id, op_id=op_id, actor=actor):
        try:
            with workspace(staging_root, op_id, failures_root=failures_root) as staging:
                result = body(handle, staging)
            handle.complete(result.summary)
            return OperationStatus.COMPLETED
        except OperationCancelled:
            handle.cancelled()
            return OperationStatus.CANCELLED
        except Exception as exc:  # noqa: BLE001 - recorded on the operation, never swallowed silently
            LOGGER.exception("Step %s failed for %s", spec.id, target or "fleet")
            handle.fail(str(exc))
            return OperationStatus.FAILED
