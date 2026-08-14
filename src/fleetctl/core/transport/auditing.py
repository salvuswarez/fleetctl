"""Transport decorator that records every effect it passes through."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from fleetctl.core.effects import Capability, Effect
from fleetctl.core.errors import TransportError
from fleetctl.core.observability.audit import AuditEvent, AuditKind, ChainedAuditWriter, Outcome
from fleetctl.core.transport.base import Transport


class AuditingTransport:
    """Wraps any `Transport`, recording each call as an audit event.

    **PARAMETERS:**
        `inner` (Transport): The transport actually doing the work.  <br>
        `writer` (ChainedAuditWriter): Where records are chained and persisted.  <br>
    """

    def __init__(self, inner: Transport, writer: ChainedAuditWriter) -> None:
        self._inner = inner
        self._writer = writer

    @property
    def target(self) -> str:
        """RETURNS: str: Address or id of the wrapped transport's device."""
        return self._inner.target

    def capabilities(self) -> frozenset[Capability]:
        """RETURNS: frozenset[Capability]: Whatever the wrapped transport supports."""
        return self._inner.capabilities()

    def close(self) -> None:
        """Close the wrapped transport."""
        self._inner.close()

    def is_online(self, timeout_s: float = 3.0) -> bool:
        """RETURNS: bool: Whether the device responded. Not audited — a reachability probe changes nothing."""
        return self._inner.is_online(timeout_s=timeout_s)

    def exec(self, command: str, *, effect: Effect = Effect.MUTATING, timeout_s: float | None = None) -> str:
        """Run a command through the wrapped transport, recording the outcome."""
        return self._record(AuditKind.EXEC, command, effect, lambda: self._inner.exec(command, effect=effect, timeout_s=timeout_s))

    def exec_ok(self, command: str, *, effect: Effect = Effect.MUTATING, timeout_s: float | None = None) -> str:
        """Run a command, returning `""` on failure, recording the outcome either way."""
        started = time.monotonic()
        try:
            result = self._inner.exec(command, effect=effect, timeout_s=timeout_s)
        except TransportError as exc:
            # The failure is invisible to the caller by design, so the audit
            # record is the only place it survives. Inferring this from an
            # empty return value would be wrong: plenty of commands succeed
            # silently.
            self._emit(AuditKind.EXEC, command, effect, Outcome.SKIPPED, started, None, error=str(exc))
            return ""
        self._emit(AuditKind.EXEC, command, effect, Outcome.OK, started, None)
        return result

    def put(self, local_path: Path, remote_path: str, *, effect: Effect = Effect.MUTATING) -> int:
        """Upload a file through the wrapped transport, recording the outcome."""
        return self._record(
            AuditKind.PUT,
            f"put {remote_path}",
            effect,
            lambda: self._inner.put(local_path, remote_path, effect=effect),
            detail={"local_path": str(local_path), "remote_path": remote_path},
        )

    def get(self, remote_path: str, local_path: Path) -> int:
        """Download a file through the wrapped transport, recording the outcome."""
        return self._record(
            AuditKind.GET,
            f"get {remote_path}",
            Effect.READ,
            lambda: self._inner.get(remote_path, local_path),
            detail={"remote_path": remote_path, "local_path": str(local_path)},
        )

    def free_bytes(self, remote_path: str) -> int:
        """RETURNS: int: Free bytes reported by the wrapped transport. Not audited — a read-only measurement."""
        return self._inner.free_bytes(remote_path)

    def _record[T](
        self,
        kind: AuditKind,
        action: str,
        effect: Effect,
        call: Callable[[], T],
        *,
        detail: dict[str, object] | None = None,
    ) -> T:
        """Run `call`, writing an audit record when `effect` warrants one."""
        started = time.monotonic()
        try:
            result = call()
        except TransportError as exc:
            self._emit(kind, action, effect, Outcome.FAILED, started, detail, error=str(exc))
            raise
        self._emit(kind, action, effect, Outcome.OK, started, detail)
        return result

    def _emit(
        self,
        kind: AuditKind,
        action: str,
        effect: Effect,
        outcome: Outcome,
        started: float,
        detail: dict[str, object] | None,
        *,
        error: str | None = None,
    ) -> None:
        if not effect.is_auditable:
            return
        self._writer.write(
            AuditEvent.build(
                kind,
                action,
                effect=effect,
                outcome=outcome,
                target=self._inner.target,
                detail=detail or {},
                error=error,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        )
