"""Tests for the fake transport and the capability/effect contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleetctl.core.effects import Capability, Effect, missing_capabilities
from fleetctl.core.errors import CommandFailedError, UnsupportedCapabilityError
from fleetctl.core.transport.base import CommandRunner, Transport
from fleetctl.core.transport.fake import FakeTransport


def test_fake_transport_satisfies_the_protocols() -> None:
    """Structural typing: no inheritance, and a probe can depend on the
    narrow `CommandRunner` rather than all of `Transport`."""
    # Arrange
    transport = FakeTransport()

    # Act / Assert
    assert isinstance(transport, Transport)
    assert isinstance(transport, CommandRunner)


def test_an_unscripted_command_raises_rather_than_returning_empty() -> None:
    """ "No output" and "never scripted" must be distinguishable, or a test
    silently exercises the wrong path."""
    # Arrange
    transport = FakeTransport()

    # Act / Assert
    with pytest.raises(CommandFailedError):
        transport.exec("getprop ro.product.model")


def test_exec_ok_converts_failure_to_empty_string() -> None:
    # Arrange
    transport = FakeTransport(failures={"boom": "nope"})

    # Act
    actual = transport.exec_ok("boom")

    # Assert
    assert actual == ""


def test_calls_record_the_declared_effect() -> None:
    # Arrange
    transport = FakeTransport(responses={"rm -rf /sdcard/x": ""})

    # Act
    transport.exec("rm -rf /sdcard/x", effect=Effect.DESTRUCTIVE)

    # Assert
    assert transport.calls[0].effect is Effect.DESTRUCTIVE


def test_an_undeclared_capability_raises_instead_of_silently_no_oping() -> None:
    # Arrange
    transport = FakeTransport(supported=frozenset({Capability.REACH}))

    # Act / Assert
    with pytest.raises(UnsupportedCapabilityError) as caught:
        transport.exec("anything")
    assert caught.value.capability == "exec"


def test_put_reports_the_source_size(tmp_path: Path) -> None:
    # Arrange
    payload = tmp_path / "archive.tar.gz"
    payload.write_bytes(b"y" * 64)
    transport = FakeTransport()

    # Act
    actual = transport.put(payload, "/sdcard/archive.tar.gz")

    # Assert
    assert actual == 64


def test_get_writes_scripted_content_and_creates_parents(tmp_path: Path) -> None:
    # Arrange
    transport = FakeTransport(responses={"/sdcard/a.xml": "<a/>"})
    destination = tmp_path / "nested" / "a.xml"

    # Act
    actual = transport.get("/sdcard/a.xml", destination)

    # Assert
    assert actual == 4
    assert destination.read_text(encoding="utf-8") == "<a/>"


@pytest.mark.parametrize(
    ("effect", "auditable"),
    [(Effect.READ, False), (Effect.MUTATING, True), (Effect.DESTRUCTIVE, True)],
)
def test_only_changing_effects_are_auditable(effect: Effect, auditable: bool) -> None:
    # Act / Assert
    assert effect.is_auditable is auditable


def test_missing_capabilities_reports_the_unsatisfied_subset() -> None:
    # Arrange
    required = frozenset({Capability.EXEC, Capability.FILES, Capability.STATE})
    provided = frozenset({Capability.EXEC, Capability.REACH})

    # Act
    actual = missing_capabilities(required, provided)

    # Assert
    assert actual == frozenset({Capability.FILES, Capability.STATE})
