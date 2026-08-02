"""Tests for audit events, the hash chain, and the JSONL sink."""

from __future__ import annotations

import json
import threading
from dataclasses import replace
from pathlib import Path

from fleetctl.core.effects import Effect
from fleetctl.core.observability.audit import (
    GENESIS_HASH,
    AuditEvent,
    AuditKind,
    ChainedAuditWriter,
    InMemoryAuditSink,
    JsonlAuditSink,
    Outcome,
    verify_chain,
)
from fleetctl.core.observability.correlation import correlate
from fleetctl.core.observability.redact import MASK


def test_build_stamps_the_active_correlation() -> None:
    # Arrange / Act
    with correlate(run_id="r1", step_id="s1", op_id="o1", actor="cli:alice"):
        event = AuditEvent.build(AuditKind.EXEC, "pm list packages")

    # Assert
    assert (event.run_id, event.step_id, event.op_id, event.actor) == ("r1", "s1", "o1", "cli:alice")
    assert event.ts != ""


def test_writer_chains_records_from_genesis() -> None:
    # Arrange
    sink = InMemoryAuditSink()
    writer = ChainedAuditWriter(sink)

    # Act
    for index in range(3):
        writer.write(AuditEvent.build(AuditKind.EXEC, f"cmd-{index}"))
    written = sink.read_all()

    # Assert
    assert [event.seq for event in written] == [0, 1, 2]
    assert written[0].prev_hash == GENESIS_HASH
    assert written[1].prev_hash == written[0].hash
    assert written[2].prev_hash == written[1].hash
    assert verify_chain(written) == (True, None)


def test_verify_detects_a_tampered_record() -> None:
    # Arrange
    sink = InMemoryAuditSink()
    writer = ChainedAuditWriter(sink)
    for index in range(3):
        writer.write(AuditEvent.build(AuditKind.EXEC, f"cmd-{index}"))
    written = sink.read_all()

    # Act
    written[1] = replace(written[1], action="something-else")
    intact, first_bad = verify_chain(written)

    # Assert
    assert intact is False
    assert first_bad == 1


def test_verify_detects_a_removed_record() -> None:
    # Arrange
    sink = InMemoryAuditSink()
    writer = ChainedAuditWriter(sink)
    for index in range(3):
        writer.write(AuditEvent.build(AuditKind.EXEC, f"cmd-{index}"))
    written = sink.read_all()

    # Act
    intact, first_bad = verify_chain([written[0], written[2]])

    # Assert
    assert intact is False
    assert first_bad == 2


def test_writer_redacts_before_hashing_so_what_is_verified_is_what_was_written() -> None:
    # Arrange
    sink = InMemoryAuditSink()
    writer = ChainedAuditWriter(sink)

    # Act
    writer.write(AuditEvent.build(AuditKind.EXEC, "curl http://admin:hunter2@192.168.1.50/", detail={"password": "hunter2"}))
    written = sink.read_all()

    # Assert
    assert "hunter2" not in written[0].action
    assert written[0].detail["password"] == MASK
    assert verify_chain(written) == (True, None)


def test_concurrent_writes_produce_an_unbroken_chain() -> None:
    """A hash chain needs a total order over a single writer. Steps run
    concurrently, so this is the property that keeps `audit verify` from
    crying wolf."""
    # Arrange
    sink = InMemoryAuditSink()
    writer = ChainedAuditWriter(sink)

    def _write(index: int) -> None:
        writer.write(AuditEvent.build(AuditKind.EXEC, f"cmd-{index}"))

    threads = [threading.Thread(target=_write, args=(index,)) for index in range(50)]

    # Act
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Assert
    written = sink.read_all()
    assert len(written) == 50
    assert [event.seq for event in written] == list(range(50))
    assert verify_chain(written) == (True, None)


def test_jsonl_sink_round_trips_records(tmp_path: Path) -> None:
    # Arrange
    sink = JsonlAuditSink(tmp_path)
    writer = ChainedAuditWriter(sink)
    writer.write(AuditEvent.build(AuditKind.EXEC, "pm disable-user com.example", effect=Effect.DESTRUCTIVE, outcome=Outcome.OK))

    # Act
    recovered = sink.read_all()

    # Assert
    assert len(recovered) == 1
    assert recovered[0].action == "pm disable-user com.example"
    assert recovered[0].effect is Effect.DESTRUCTIVE
    assert verify_chain(recovered) == (True, None)


def test_jsonl_sink_writes_one_file_per_day(tmp_path: Path) -> None:
    # Arrange
    sink = JsonlAuditSink(tmp_path)

    # Act
    sink.write(AuditEvent.build(AuditKind.EXEC, "a", ts="2026-08-01T10:00:00+00:00"))
    sink.write(AuditEvent.build(AuditKind.EXEC, "b", ts="2026-08-02T10:00:00+00:00"))

    # Assert
    assert sorted(path.name for path in tmp_path.glob("*.jsonl")) == ["2026-08-01.jsonl", "2026-08-02.jsonl"]


def test_jsonl_sink_skips_malformed_lines_rather_than_hiding_the_trail(tmp_path: Path) -> None:
    # Arrange
    sink = JsonlAuditSink(tmp_path)
    sink.write(AuditEvent.build(AuditKind.EXEC, "good", ts="2026-08-01T10:00:00+00:00"))
    with open(tmp_path / "2026-08-01.jsonl", "a", encoding="utf-8") as handle:
        handle.write("{not json\n")
        handle.write(json.dumps({"kind": "nonsense"}) + "\n")

    # Act
    recovered = sink.read_all()

    # Assert
    assert [event.action for event in recovered] == ["good"]


def test_reading_a_missing_audit_directory_returns_nothing(tmp_path: Path) -> None:
    # Arrange
    sink = JsonlAuditSink(tmp_path / "does-not-exist")

    # Act
    recovered = sink.read_all()

    # Assert
    assert recovered == []
