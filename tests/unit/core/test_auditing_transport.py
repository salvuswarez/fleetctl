"""Tests for the auditing transport decorator.

These assert on *effects* — what the audit stream recorded — rather than on
mock call lists. That is the point of putting auditing at the transport seam:
a test can ask "did 90 destructive commands actually land, and did they
succeed?" without reaching inside anything.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleetctl.core.effects import Capability, Effect
from fleetctl.core.errors import CommandFailedError
from fleetctl.core.observability.audit import AuditKind, ChainedAuditWriter, InMemoryAuditSink, Outcome, verify_chain
from fleetctl.core.transport.auditing import AuditingTransport
from fleetctl.core.transport.fake import FakeTransport


@pytest.fixture
def sink() -> InMemoryAuditSink:
    return InMemoryAuditSink()


def _wrap(inner: FakeTransport, sink: InMemoryAuditSink) -> AuditingTransport:
    return AuditingTransport(inner, ChainedAuditWriter(sink))


def test_mutating_commands_are_recorded(sink: InMemoryAuditSink) -> None:
    # Arrange
    transport = _wrap(FakeTransport(responses={"settings put global x 0": ""}), sink)

    # Act
    transport.exec("settings put global x 0", effect=Effect.MUTATING)

    # Assert
    recorded = sink.read_all()
    assert len(recorded) == 1
    assert recorded[0].kind is AuditKind.EXEC
    assert recorded[0].action == "settings put global x 0"
    assert recorded[0].outcome is Outcome.OK
    assert recorded[0].target == "192.168.1.50"


def test_read_commands_stay_out_of_the_durable_trail(sink: InMemoryAuditSink) -> None:
    """A fleet-wide run issues thousands of probes; burying real changes
    among them is how an audit log stops being read."""
    # Arrange
    transport = _wrap(FakeTransport(responses={"getprop ro.product.model": "AFTKA"}), sink)

    # Act
    transport.exec("getprop ro.product.model", effect=Effect.READ)

    # Assert
    assert sink.read_all() == []


def test_a_failed_command_is_recorded_and_the_error_still_propagates(sink: InMemoryAuditSink) -> None:
    # Arrange
    transport = _wrap(FakeTransport(failures={"pm install bad.apk": "no space"}), sink)

    # Act
    with pytest.raises(CommandFailedError):
        transport.exec("pm install bad.apk", effect=Effect.DESTRUCTIVE)

    # Assert
    recorded = sink.read_all()
    assert recorded[0].outcome is Outcome.FAILED
    assert "no space" in (recorded[0].error or "")


def test_a_swallowed_failure_is_recorded_as_skipped(sink: InMemoryAuditSink) -> None:
    """`pm disable-user` silently no-ops on old Fire OS. `exec_ok` hides that
    from the caller, so the audit trail is the only place it survives."""
    # Arrange
    inner = FakeTransport(failures={"pm disable-user --user 0 com.amazon.example": "SecurityException"})
    transport = _wrap(inner, sink)

    # Act
    result = transport.exec_ok("pm disable-user --user 0 com.amazon.example", effect=Effect.DESTRUCTIVE)

    # Assert
    assert result == ""
    recorded = sink.read_all()
    assert recorded[0].outcome is Outcome.SKIPPED


def test_a_batch_of_destructive_commands_is_individually_accounted_for(sink: InMemoryAuditSink) -> None:
    """The predecessor logged one line for ~90 package disables and verified
    none of them. This is the regression test for that whole class of gap."""
    # Arrange
    packages = [f"com.example.bloat{index}" for index in range(90)]
    blocked = {f"pm disable-user --user 0 {packages[index]}": "SecurityException" for index in (3, 17, 42)}
    allowed = {f"pm disable-user --user 0 {package}": "" for package in packages}
    transport = _wrap(FakeTransport(responses=allowed, failures=blocked), sink)

    # Act
    for package in packages:
        transport.exec_ok(f"pm disable-user --user 0 {package}", effect=Effect.DESTRUCTIVE)

    # Assert
    recorded = sink.read_all()
    assert len(recorded) == 90
    assert sum(1 for event in recorded if event.outcome is Outcome.OK) == 87
    assert sum(1 for event in recorded if event.outcome is Outcome.SKIPPED) == 3
    assert verify_chain(recorded) == (True, None)


def test_uploads_are_recorded_with_both_paths(sink: InMemoryAuditSink, tmp_path: Path) -> None:
    # Arrange
    payload = tmp_path / "build.tar.gz"
    payload.write_bytes(b"x" * 128)
    transport = _wrap(FakeTransport(), sink)

    # Act
    written = transport.put(payload, "/sdcard/build.tar.gz", effect=Effect.DESTRUCTIVE)

    # Assert
    assert written == 128
    recorded = sink.read_all()
    assert recorded[0].kind is AuditKind.PUT
    assert recorded[0].detail["remote_path"] == "/sdcard/build.tar.gz"


def test_downloads_are_not_audited_but_still_work(sink: InMemoryAuditSink, tmp_path: Path) -> None:
    # Arrange
    transport = _wrap(FakeTransport(responses={"/sdcard/guisettings.xml": "<settings/>"}), sink)
    destination = tmp_path / "pulled.xml"

    # Act
    transport.get("/sdcard/guisettings.xml", destination)

    # Assert
    assert destination.read_text(encoding="utf-8") == "<settings/>"
    assert sink.read_all() == []


def test_credentials_in_a_command_never_reach_the_audit_record(sink: InMemoryAuditSink) -> None:
    """Redaction happens inside the decorator, so a step author cannot
    bypass it by forgetting."""
    # Arrange
    command = "sed -i 's|m3uPath|http://bob:hunter2@iptv.example.com/get.php|' /sdcard/settings.xml"
    transport = _wrap(FakeTransport(responses={command: ""}), sink)

    # Act
    transport.exec(command, effect=Effect.MUTATING)

    # Assert
    assert "hunter2" not in sink.read_all()[0].action


def test_the_decorator_passes_through_capabilities_and_close(sink: InMemoryAuditSink) -> None:
    # Arrange
    inner = FakeTransport(supported=frozenset({Capability.EXEC}))
    transport = _wrap(inner, sink)

    # Act
    capabilities = transport.capabilities()
    transport.close()

    # Assert
    assert capabilities == frozenset({Capability.EXEC})
    assert inner.closed is True


def test_reachability_and_free_space_are_passed_through_unaudited(sink: InMemoryAuditSink) -> None:
    # Arrange
    transport = _wrap(FakeTransport(online=True, free_space=4096), sink)

    # Act
    online = transport.is_online()
    free = transport.free_bytes("/sdcard")

    # Assert
    assert online is True
    assert free == 4096
    assert sink.read_all() == []
