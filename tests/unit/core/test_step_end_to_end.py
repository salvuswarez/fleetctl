"""The S1 exit criterion.

A step runs end to end against `FakeTransport` and `LocalArtifactStore`, with
its audit records asserted — no device, no network, no SMB share. If this
test is possible, the seams are real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleetctl.core.artifacts.ref import ArtifactRef
from fleetctl.core.artifacts.store import LocalArtifactStore
from fleetctl.core.effects import Capability, Effect
from fleetctl.core.errors import FleetError
from fleetctl.core.inventory.device import Device
from fleetctl.core.inventory.store import DeviceStore
from fleetctl.core.observability.audit import ChainedAuditWriter, InMemoryAuditSink, Outcome, verify_chain
from fleetctl.core.operations.registry import OperationHandle, OperationRegistry, OperationStatus
from fleetctl.core.transport.auditing import AuditingTransport
from fleetctl.core.transport.base import Transport
from fleetctl.core.transport.fake import FakeTransport
from fleetctl.core.workflow.runner import check_capabilities, run_step
from fleetctl.core.workflow.step import DeviceStepContext, StepResult, StepSpec

CLEANUP = StepSpec(
    id="demo.cleanup",
    summary="Trim caches and record what was freed.",
    effect=Effect.DESTRUCTIVE,
    requires=frozenset({Capability.EXEC, Capability.CLEANUP}),
    scope="device",
)


def _cleanup_step(context: DeviceStepContext) -> StepResult:
    """A step body of the shape every real pack will use."""
    context.handle.log(f"Cleaning {context.device.name}...")
    context.handle.check_cancelled()

    freed = context.transport.exec("df -k /cache", effect=Effect.READ)
    for path in context.config.get("prune_paths", []):
        context.transport.exec_ok(f"rm -rf {path}", effect=Effect.DESTRUCTIVE)

    context.handle.log("Cleanup complete")
    return StepResult(summary=f"Cleaned {context.device.id}", facts={"free": freed})


class _NullApps:
    """An app manager that refuses to be used, for steps that never touch it."""

    def installed_version(self, identifier: str) -> str:
        raise AssertionError("this step must not query installed apps")

    def install(self, package: Path, *, identifier: str = "") -> None:
        raise AssertionError("this step must not install anything")

    def stop(self, identifier: str) -> None:
        raise AssertionError("this step must not stop an app")


class _NullState:
    """A state manager that refuses to be used, for steps that never touch it."""

    platform = "test"

    def state_root(self, spec: object) -> str:
        raise AssertionError("this step must not touch device state")

    def snapshot(self, spec: object, destination: Path) -> Path:
        raise AssertionError("this step must not touch device state")

    def restore(self, spec: object, archive: Path) -> None:
        raise AssertionError("this step must not touch device state")


@pytest.fixture
def sink() -> InMemoryAuditSink:
    return InMemoryAuditSink()


@pytest.fixture
def device() -> Device:
    return Device(id="stick-1", type="firetv", address="192.168.1.50", name="Living Room", tags=["kodi"])


@pytest.fixture
def transport(sink: InMemoryAuditSink) -> Transport:
    inner = FakeTransport(
        responses={
            "df -k /cache": "Filesystem 1K-blocks Used Available\n/dev/x 100 40 60",
            "rm -rf /cache/a": "",
            "rm -rf /cache/b": "",
        },
        failures={"rm -rf /cache/locked": "Permission denied"},
    )
    return AuditingTransport(inner, ChainedAuditWriter(sink))


def _run(
    device: Device,
    transport: Transport,
    tmp_path: Path,
    *,
    prune_paths: list[str],
    registry: OperationRegistry | None = None,
) -> tuple[OperationRegistry, OperationStatus]:
    registry = registry or OperationRegistry()
    inventory = DeviceStore(tmp_path / "devices.yml")
    inventory.save([device])
    artifacts = LocalArtifactStore(tmp_path / "store")

    def body(handle: OperationHandle, staging: Path) -> StepResult:
        return _cleanup_step(
            DeviceStepContext(
                device=device,
                transport=transport,
                state=_NullState(),
                apps=_NullApps(),
                artifacts=artifacts,
                inventory=inventory,
                config={"prune_paths": prune_paths},
                handle=handle,
                workspace=staging,
            )
        )

    status = run_step(
        registry,
        CLEANUP,
        body,
        op_id="op-1",
        target=device.id,
        actor="cli:alice",
        run_id="run-1",
        staging_root=tmp_path / "staging",
    )
    return registry, status


def test_a_step_runs_end_to_end_and_reports_completed(device: Device, transport: Transport, tmp_path: Path) -> None:
    # Act
    registry, status = _run(device, transport, tmp_path, prune_paths=["/cache/a", "/cache/b"])

    # Assert
    assert status is OperationStatus.COMPLETED
    operation = registry.get("op-1")
    assert operation is not None
    assert operation.result == "Cleaned stick-1"
    assert [entry["message"] for entry in operation.logs] == ["Cleaning Living Room...", "Cleanup complete"]


def test_the_audit_trail_records_only_the_changing_commands(device: Device, transport: Transport, tmp_path: Path, sink: InMemoryAuditSink) -> None:
    # Act
    _run(device, transport, tmp_path, prune_paths=["/cache/a", "/cache/b"])

    # Assert
    recorded = sink.read_all()
    assert [event.action for event in recorded] == ["rm -rf /cache/a", "rm -rf /cache/b"]
    assert all(event.effect is Effect.DESTRUCTIVE for event in recorded)
    assert all(event.outcome is Outcome.OK for event in recorded)
    assert verify_chain(recorded) == (True, None)


def test_audit_records_carry_the_full_correlation_and_actor(device: Device, transport: Transport, tmp_path: Path, sink: InMemoryAuditSink) -> None:
    """Bound by the runner, so a step author writes no correlation code."""
    # Act
    _run(device, transport, tmp_path, prune_paths=["/cache/a"])

    # Assert
    event = sink.read_all()[0]
    assert (event.run_id, event.step_id, event.op_id, event.actor) == ("run-1", "demo.cleanup", "op-1", "cli:alice")
    assert event.target == "192.168.1.50"


def test_a_silently_swallowed_failure_still_reaches_the_audit_trail(device: Device, transport: Transport, tmp_path: Path, sink: InMemoryAuditSink) -> None:
    """The step sees `""` and carries on; the record is the only survivor."""
    # Act
    _, status = _run(device, transport, tmp_path, prune_paths=["/cache/a", "/cache/locked"])

    # Assert
    assert status is OperationStatus.COMPLETED
    outcomes = {event.action: event.outcome for event in sink.read_all()}
    assert outcomes["rm -rf /cache/a"] is Outcome.OK
    assert outcomes["rm -rf /cache/locked"] is Outcome.SKIPPED


def test_correlation_does_not_leak_out_of_the_run(device: Device, transport: Transport, tmp_path: Path) -> None:
    # Arrange
    from fleetctl.core.observability.correlation import current

    # Act
    _run(device, transport, tmp_path, prune_paths=["/cache/a"])

    # Assert
    assert current().run_id == "-"


def test_a_failing_step_is_recorded_and_does_not_raise(device: Device, tmp_path: Path, sink: InMemoryAuditSink) -> None:
    """One failing device must not abort a fleet-wide run."""
    # Arrange
    transport = AuditingTransport(FakeTransport(), ChainedAuditWriter(sink))

    # Act
    registry, status = _run(device, transport, tmp_path, prune_paths=[])

    # Assert
    assert status is OperationStatus.FAILED
    operation = registry.get("op-1")
    assert operation is not None
    assert "df -k /cache" in (operation.result or "")


def test_a_cancelled_step_reports_its_own_outcome(device: Device, transport: Transport, tmp_path: Path) -> None:
    """Cancellation is cooperative: the flag is set, and the step reports
    when it observes it, so the record cannot contradict what ran."""
    # Arrange
    registry = OperationRegistry()
    registry.start("op-1", CLEANUP.id, device.id)
    registry.request_cancel("op-1")

    # Act
    _, status = _run(device, transport, tmp_path, prune_paths=["/cache/a"], registry=registry)

    # Assert
    assert status is OperationStatus.CANCELLED


def test_the_workspace_is_removed_after_the_step(device: Device, transport: Transport, tmp_path: Path) -> None:
    # Act
    _run(device, transport, tmp_path, prune_paths=["/cache/a"])

    # Assert
    assert list((tmp_path / "staging").iterdir()) == []


def test_capabilities_are_checked_before_anything_is_touched(sink: InMemoryAuditSink) -> None:
    # Arrange
    limited = AuditingTransport(FakeTransport(supported=frozenset({Capability.EXEC})), ChainedAuditWriter(sink))

    # Act / Assert
    with pytest.raises(FleetError) as caught:
        check_capabilities(CLEANUP, limited)
    assert "cleanup" in str(caught.value)
    assert sink.read_all() == []


def test_capability_check_passes_when_the_transport_provides_everything(transport: Transport) -> None:
    # Act / Assert
    check_capabilities(CLEANUP, transport)


def test_a_step_can_hand_an_artifact_to_a_later_step(tmp_path: Path) -> None:
    """A bare summary string could not carry this, which is what made the
    predecessor's `-> str` return type a dead end."""
    # Arrange
    ref = ArtifactRef(kind="builds", name="build_1.tar.gz")

    # Act
    result = StepResult(summary="Built", artifacts={"build": ref})

    # Assert
    assert result.artifacts["build"].wire == "builds/build_1.tar.gz"


def test_a_failed_step_preserves_its_workspace_for_diagnosis(device: Device, tmp_path: Path) -> None:
    """The predecessor tore the workspace down on every path, destroying the
    archive that had just failed to deploy."""
    # Arrange
    registry = OperationRegistry()
    failures = tmp_path / "forensics"

    def body(handle: OperationHandle, staging: Path) -> StepResult:
        (staging / "failed-build.tar.gz").write_bytes(b"partial")
        raise RuntimeError("extract failed")

    # Act
    status = run_step(
        registry,
        CLEANUP,
        body,
        op_id="op-9",
        target=device.id,
        staging_root=tmp_path / "staging",
        failures_root=failures,
    )

    # Assert
    assert status is OperationStatus.FAILED
    assert (failures / "op-9" / "failed-build.tar.gz").read_bytes() == b"partial"
    assert list((tmp_path / "staging").iterdir()) == []
