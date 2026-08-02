"""Operation records: the human-readable timeline, distinct from the audit trail."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from ..errors import OperationCancelled

_MAX_OPERATIONS = 500


class OperationStatus(str, Enum):
    """Lifecycle states for a tracked operation."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """RETURNS: bool: Whether no further transition is expected."""
        return self is not OperationStatus.RUNNING


@dataclass(slots=True)
class Operation:
    """One tracked unit of work.

    **PARAMETERS:**
        `id` (str): Unique operation id.  <br>
        `step_id` (str): Which step is running.  <br>
        `target` (str): Device id or address, empty for fleet-level work.  <br>
        `status` (OperationStatus): Current lifecycle state.  <br>
        `logs` (list[dict[str, str]]): Ordered ``{time, message}`` entries.  <br>
        `started_at` (str): ISO-8601 start timestamp.  <br>
        `completed_at` (str | None): ISO-8601 completion timestamp, when finished.  <br>
        `result` (str | None): Human-readable summary or error.  <br>
        `params` (dict[str, Any]): The flags it ran with, so a rerun repeats it rather than approximating it.  <br>
        `facts` (dict[str, Any]): Structured values the step reported, e.g. a discovered version.  <br>
    """

    id: str
    step_id: str
    target: str = ""
    status: OperationStatus = OperationStatus.RUNNING
    params: dict[str, Any] = field(default_factory=dict)
    facts: dict[str, Any] = field(default_factory=dict)
    logs: list[dict[str, str]] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    result: str | None = None

    def snapshot(self) -> dict[str, Any]:
        """RETURNS: dict[str, Any]: A JSON-safe copy, safe to serialize while a worker keeps appending logs."""
        return {
            "id": self.id,
            "step_id": self.step_id,
            "target": self.target,
            "status": self.status.value,
            "params": dict(self.params),
            "facts": dict(self.facts),
            "logs": list(self.logs),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": self.result,
        }


class OperationHandle:
    """What running work receives: log, check cancellation, finish.

    **PARAMETERS:**
        `registry` (OperationRegistry): The owning registry.  <br>
        `op_id` (str): The operation this handle controls.  <br>
    """

    def __init__(self, registry: OperationRegistry, op_id: str) -> None:
        self.op_id = op_id
        self._registry = registry

    def log(self, message: str) -> None:
        """Append a timeline entry."""
        self._registry.append_log(self.op_id, message)

    def check_cancelled(self) -> None:
        """Raise if cancellation has been requested.

        **RAISES:**
            `OperationCancelled`: If a cancel was requested for this operation.  <br>
        """
        if self._registry.is_cancel_requested(self.op_id):
            raise OperationCancelled(self.op_id)

    def complete(self, result: str | None, facts: Mapping[str, Any] | None = None) -> None:
        """Mark this operation completed, keeping any structured values it reported."""
        self._registry.finish(self.op_id, OperationStatus.COMPLETED, result, facts)

    def fail(self, result: str) -> None:
        """Mark this operation failed."""
        self._registry.finish(self.op_id, OperationStatus.FAILED, result)

    def cancelled(self) -> None:
        """Mark this operation cancelled, having observed the request."""
        self._registry.finish(self.op_id, OperationStatus.CANCELLED, "Cancelled")


class OperationRegistry:
    """In-memory operation table with one owning lock and bounded retention."""

    def __init__(self, max_operations: int = _MAX_OPERATIONS) -> None:
        self._lock = threading.Lock()
        self._operations: dict[str, Operation] = {}
        self._cancel_requested: set[str] = set()
        self._max_operations = max_operations
        self._sequence = 0

    def new_id(self, prefix: str) -> str:
        """Mint an operation id that cannot collide with a live one.

        A timestamp alone is not enough: rerunning a step within the same
        second reused the id and replaced the record it was rerun from.

        **PARAMETERS:**
            `prefix` (str): Readable lead, normally actor and step.  <br>

        **RETURNS:**
            `str`: The new id.  <br>
        """
        with self._lock:
            self._sequence += 1
            return f"{prefix}-{int(time.time())}-{self._sequence}"

    def start(self, op_id: str, step_id: str, target: str = "", params: Mapping[str, Any] | None = None) -> OperationHandle:
        """Register a running operation and return its handle.

        **PARAMETERS:**
            `op_id` (str): Unique operation id.  <br>
            `step_id` (str): Which step is running.  <br>
            `target` (str): Device id or address, empty for fleet-level work.  <br>
            `params` (Mapping[str, Any] | None): Flags this run was given, recorded so a rerun can repeat it exactly.  <br>

        **RETURNS:**
            `OperationHandle`: Handle for the work to report through.  <br>
        """
        with self._lock:
            self._operations[op_id] = Operation(id=op_id, step_id=step_id, target=target, params=dict(params or {}))
            self._evict_locked()
        return OperationHandle(self, op_id)

    def get(self, op_id: str) -> Operation | None:
        """RETURNS: Operation | None: The operation, if tracked."""
        with self._lock:
            return self._operations.get(op_id)

    def all_snapshots(self) -> dict[str, dict[str, Any]]:
        """RETURNS: dict[str, dict[str, Any]]: Wire-safe snapshots of every tracked operation."""
        with self._lock:
            return {op_id: operation.snapshot() for op_id, operation in self._operations.items()}

    def running_for(self, target: str) -> str | None:
        """RETURNS: str | None: Id of a running operation against `target`, if any."""
        with self._lock:
            for operation in self._operations.values():
                if operation.target == target and operation.status is OperationStatus.RUNNING:
                    return operation.id
        return None

    def request_cancel(self, op_id: str) -> bool:
        """Ask a running operation to stop at its next step boundary.

        **RETURNS:**
            `bool`: False if `op_id` is unknown or already finished.  <br>
        """
        with self._lock:
            operation = self._operations.get(op_id)
            if operation is None or operation.status is not OperationStatus.RUNNING:
                return False
            self._cancel_requested.add(op_id)
            return True

    def is_cancel_requested(self, op_id: str) -> bool:
        """RETURNS: bool: Whether cancellation was requested for `op_id`."""
        with self._lock:
            return op_id in self._cancel_requested

    def append_log(self, op_id: str, message: str) -> None:
        """Append a timeline entry to `op_id`, ignoring unknown ids."""
        with self._lock:
            operation = self._operations.get(op_id)
            if operation is not None:
                operation.logs.append({"time": datetime.now(timezone.utc).isoformat(), "message": message})

    def finish(self, op_id: str, status: OperationStatus, result: str | None, facts: Mapping[str, Any] | None = None) -> None:
        """Record a terminal state for `op_id`, ignoring unknown ids."""
        with self._lock:
            operation = self._operations.get(op_id)
            if operation is None:
                return
            operation.facts = dict(facts or {})
            operation.status = status
            operation.result = result
            operation.completed_at = datetime.now(timezone.utc).isoformat()
            self._cancel_requested.discard(op_id)

    def _evict_locked(self) -> None:
        """Drop the oldest finished operations. Running work is never evicted."""
        if len(self._operations) <= self._max_operations:
            return
        finished = sorted(
            (operation for operation in self._operations.values() if operation.status.is_terminal),
            key=lambda operation: operation.started_at,
        )
        for operation in finished[: len(self._operations) - self._max_operations]:
            self._operations.pop(operation.id, None)
