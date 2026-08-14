"""The audit trail: what actually happened, to what, and whether it worked."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

from fleetctl.core.effects import Effect
from fleetctl.core.observability.correlation import current
from fleetctl.core.observability.redact import Redactor

LOGGER = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64


class AuditKind(str, Enum):
    """What sort of thing an audit record describes."""

    EXEC = "exec"
    PUT = "put"
    GET = "get"
    PLAN = "plan"
    CONFIG = "config"
    DECISION = "decision"
    AUTH = "auth"


class Outcome(str, Enum):
    """How an audited action ended."""

    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"
    DENIED = "denied"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One recorded effect. Never updated after it is written.

    **PARAMETERS:**
        `kind` (AuditKind): What sort of action this was.  <br>
        `action` (str): What was done, e.g. a command or ``artifact.put``.  <br>
        `effect` (Effect): How much it changed on the target.  <br>
        `outcome` (Outcome): How it ended.  <br>
        `target` (str): Device address or id, when there was one.  <br>
        `detail` (Mapping[str, Any]): Extra structured context. Redacted before writing.  <br>
        `error` (str | None): Failure summary, when `outcome` is not `Outcome.OK`.  <br>
        `duration_ms` (int): Wall-clock duration.  <br>
        `ts` (str): ISO-8601 UTC timestamp.  <br>
        `run_id` (str): Correlation — one workflow invocation.  <br>
        `step_id` (str): Correlation — one step.  <br>
        `op_id` (str): Correlation — one (step, device) pair.  <br>
        `actor` (str): Who initiated the run.  <br>
        `seq` (int): Position within the destination file.  <br>
        `prev_hash` (str): Hash of the preceding record in the same file.  <br>
        `hash` (str): This record's hash, covering `prev_hash`.  <br>
    """

    kind: AuditKind
    action: str
    effect: Effect = Effect.MUTATING
    outcome: Outcome = Outcome.OK
    target: str = ""
    detail: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0
    ts: str = ""
    run_id: str = ""
    step_id: str = ""
    op_id: str = ""
    actor: str = ""
    seq: int = 0
    prev_hash: str = ""
    hash: str = ""

    @classmethod
    def build(cls, kind: AuditKind, action: str, **overrides: Any) -> AuditEvent:
        """Create an event stamped with the current time and correlation.

        **PARAMETERS:**
            `kind` (AuditKind): What sort of action this was.  <br>
            `action` (str): What was done.  <br>
            `**overrides` (Any): Any other `AuditEvent` field.  <br>

        **RETURNS:**
            `AuditEvent`: An unchained event, ready to hand to a sink.  <br>
        """
        active = current()
        stamped: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": active.run_id,
            "step_id": active.step_id,
            "op_id": active.op_id,
            "actor": active.actor,
        }
        stamped.update(overrides)
        return cls(kind=kind, action=action, **stamped)

    def to_dict(self) -> dict[str, Any]:
        """RETURNS: dict[str, Any]: JSON-serializable form, with enums as their values."""
        raw = asdict(self)
        raw["kind"] = self.kind.value
        raw["effect"] = self.effect.value
        raw["outcome"] = self.outcome.value
        raw["detail"] = dict(self.detail)
        return raw

    def digest(self) -> str:
        """Compute this record's hash over its content and `prev_hash`.

        **RETURNS:**
            `str`: Hex SHA-256 covering every field except `hash` itself.  <br>
        """
        payload = self.to_dict()
        payload.pop("hash", None)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class AuditSink(Protocol):
    """Where audit records are persisted."""

    def write(self, event: AuditEvent) -> None:
        """Append one record. Must not raise into the caller's control flow."""

    def read_all(self) -> list[AuditEvent]:
        """RETURNS: list[AuditEvent]: Every record this sink holds, in write order."""


class InMemoryAuditSink:
    """Audit sink that keeps records in a list. For tests and dry runs.

    The second adapter behind the audit seam, which is what makes it a seam
    rather than one implementation with an interface drawn around it.
    """

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._lock = threading.Lock()

    def write(self, event: AuditEvent) -> None:
        """Append `event` to the in-memory list."""
        with self._lock:
            self._events.append(event)

    def read_all(self) -> list[AuditEvent]:
        """RETURNS: list[AuditEvent]: A copy of the recorded events."""
        with self._lock:
            return list(self._events)


class JsonlAuditSink:
    """Audit sink writing one JSON object per line, one file per UTC day.

    **PARAMETERS:**
        `directory` (Path): Where daily ``YYYY-MM-DD.jsonl`` files are written.  <br>
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._lock = threading.Lock()

    def path_for(self, ts: str) -> Path:
        """RETURNS: Path: The daily file an event with timestamp `ts` belongs in."""
        day = ts[:10] if len(ts) >= 10 else datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._directory / f"{day}.jsonl"

    def write(self, event: AuditEvent) -> None:
        """Append `event` as one JSON line to its day's file."""
        path = self.path_for(event.ts)
        with self._lock:
            self._directory.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(event.to_dict(), default=str) + "\n")

    def read_all(self) -> list[AuditEvent]:
        """Read every record across every daily file, oldest file first.

        **RETURNS:**
            `list[AuditEvent]`: Parsed records. Malformed lines are skipped rather than aborting the read, so one corrupt line cannot hide the rest of the trail.  <br>
        """
        events: list[AuditEvent] = []
        if not self._directory.is_dir():
            return events
        for path in sorted(self._directory.glob("*.jsonl")):
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    parsed = _parse_line(line)
                    if parsed is not None:
                        events.append(parsed)
        return events


def _parse_line(line: str) -> AuditEvent | None:
    stripped = line.strip()
    if not stripped:
        return None
    try:
        raw = json.loads(stripped)
        raw["kind"] = AuditKind(raw["kind"])
        raw["effect"] = Effect(raw["effect"])
        raw["outcome"] = Outcome(raw["outcome"])
        return AuditEvent(**raw)
    except (ValueError, TypeError, KeyError):
        return None


class ChainedAuditWriter:
    """Serializes writes and links each record to the one before it.

    **PARAMETERS:**
        `sink` (AuditSink): Where chained records are handed off to.  <br>
        `redactor` (Redactor): Applied before hashing, so what is verified is what was written.  <br>
    """

    def __init__(self, sink: AuditSink, redactor: Redactor | None = None, *, resume: bool = True) -> None:
        self._sink = sink
        self._redactor = redactor or Redactor()
        self._lock = threading.Lock()
        self._seq = 0
        self._prev_hash = GENESIS_HASH
        self._resumed = not resume

    def _resume_locked(self) -> None:
        """Continue an existing chain rather than starting a new one."""
        self._resumed = True
        try:
            existing = self._sink.read_all()
        except Exception as exc:  # noqa: BLE001 - a new segment beats no trail
            LOGGER.warning("Could not read the existing audit trail, starting a new segment: %s", exc)
            return
        if existing:
            self._seq = existing[-1].seq + 1
            self._prev_hash = existing[-1].hash

    def records(self) -> list[AuditEvent]:
        """RETURNS: list[AuditEvent]: Everything the underlying sink holds, in write order."""
        return self._sink.read_all()

    def write(self, event: AuditEvent) -> AuditEvent:
        """Redact, chain, and persist `event`.

        **PARAMETERS:**
            `event` (AuditEvent): An unchained event, typically from `AuditEvent.build`.  <br>

        **RETURNS:**
            `AuditEvent`: The record as written, with `seq`, `prev_hash` and `hash` set.  <br>
        """
        with self._lock:
            if not self._resumed:
                self._resume_locked()
            chained = replace(
                event,
                action=self._redactor.text(event.action),
                detail=self._redactor.mapping(event.detail),
                error=self._redactor.text(event.error) if event.error else None,
                seq=self._seq,
                prev_hash=self._prev_hash,
            )
            chained = replace(chained, hash=chained.digest())
            self._sink.write(chained)
            self._seq += 1
            self._prev_hash = chained.hash
            return chained


def verify_chain(events: Iterable[AuditEvent]) -> tuple[bool, int | None]:
    """Check that a sequence of records forms an unbroken chain.

    **PARAMETERS:**
        `events` (Iterable[AuditEvent]): Records in write order, from one destination file.  <br>

    **RETURNS:**
        `tuple[bool, int | None]`: ``(True, None)`` when intact, otherwise ``(False, seq)`` naming the first record that failed.  <br>
    """
    expected_prev = GENESIS_HASH
    for event in events:
        # A record anchored at genesis legally starts a new segment: daily
        # rotation and retention both produce one. Tampering *within* a
        # segment is still caught, which is what the chain is for.
        if event.prev_hash == GENESIS_HASH and event.seq == 0:
            expected_prev = GENESIS_HASH
        if event.prev_hash != expected_prev or event.hash != event.digest():
            return False, event.seq
        expected_prev = event.hash
    return True, None
