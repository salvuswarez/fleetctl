"""A backgrounded step must reach a terminal status even when setup fails.

Observed on the live panel: an operation against a device that had dropped off
the network sat RUNNING with no output and ignored four cancel requests. The
transport is resolved *before* `run_step`, which is the only thing that
finishes an operation, so anything raising in between left the record running
forever.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from fleetctl.agent.toolkit import Toolkit
from fleetctl.cli.bootstrap import build_container
from fleetctl.core.effects import Capability, Effect
from fleetctl.core.errors import TransportError
from fleetctl.core.inventory.device import Device
from fleetctl.core.operations.registry import OperationStatus
from fleetctl.core.registry import RegisteredStep, Registry
from fleetctl.core.transport.base import CommandRunner, Transport
from fleetctl.core.workflow.step import DeviceStepContext, StepResult, StepSpec

TOUCH = StepSpec(id="stub.touch", summary="Touch it.", effect=Effect.READ, requires=frozenset({Capability.EXEC}), scope="device")
DEVICES = "devices:\n  - id: stub-1\n    type: stub\n    address: 192.168.1.50\n"


class _UnreachablePack:
    """A pack whose device is off the network, like a powered-down Shield."""

    id = "stub"
    platform = "stub"
    capabilities = frozenset({Capability.EXEC})
    probe_priority = 5
    app_profiles: dict[str, str] = {}

    def probe(self, runner: CommandRunner) -> dict[str, str] | None:
        return None

    def transport_for(self, device: Device, settings: Any) -> Transport:
        raise TransportError(f"{device.address} is not reachable on port 5555", target=device.address)

    def steps(self) -> Iterable[RegisteredStep]:
        return [RegisteredStep(spec=TOUCH, run=self._touch, provider=self.id)]

    def _touch(self, context: DeviceStepContext) -> StepResult:
        raise AssertionError("the body must never run for an unreachable device")


def _toolkit(tmp_path: Path) -> Toolkit:
    (tmp_path / "config" / "inventory").mkdir(parents=True)
    (tmp_path / "config" / "fleet.yml").write_text("{}\n", encoding="utf-8")
    (tmp_path / "config" / "inventory" / "devices.yml").write_text(DEVICES, encoding="utf-8")

    registry = Registry()
    registry.register_device_pack(_UnreachablePack())
    container = build_container(config_dir=tmp_path / "config", home=tmp_path / "home", actor="ha:test", registry=registry)
    return Toolkit(container=container, actor="ha:test")


def _await_terminal(toolkit: Toolkit, op_id: str, timeout: float = 10.0) -> dict[str, Any]:
    """RETURNS: dict[str, Any]: The operation's snapshot once it stops running."""
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        snapshot = toolkit.get_operation(op_id) or {}
        # A missing record is not a terminal state: the worker registers the
        # operation itself when setup fails, so polling has to keep waiting
        # through the window where the id exists and the record does not.
        status = snapshot.get("status")
        if status is not None and status != OperationStatus.RUNNING.value:
            return snapshot
        time.sleep(0.05)
    return toolkit.get_operation(op_id) or {}


def test_an_unreachable_device_fails_the_operation_rather_than_hanging(tmp_path: Path) -> None:
    """The load-bearing assertion. RUNNING forever is worse than failing: it
    blocks the device as busy and cannot be cancelled."""
    # Arrange
    toolkit = _toolkit(tmp_path)

    # Act
    started = toolkit.start_step("stub.touch", device_id="stub-1")
    snapshot = _await_terminal(toolkit, started["op_id"])

    # Assert
    assert snapshot.get("status") == OperationStatus.FAILED.value


def test_the_failure_says_what_went_wrong(tmp_path: Path) -> None:
    """ "This operation produced no output" is what the panel showed, because
    nothing ever wrote to the timeline."""
    # Arrange
    toolkit = _toolkit(tmp_path)

    # Act
    started = toolkit.start_step("stub.touch", device_id="stub-1")
    snapshot = _await_terminal(toolkit, started["op_id"])

    # Assert
    rendered = f"{snapshot.get('result', '')} {snapshot.get('logs', [])}"
    assert "not reachable" in rendered


def test_the_device_is_not_left_busy_after_a_failed_start(tmp_path: Path) -> None:
    """A stuck RUNNING operation makes `running_for` report the device busy,
    so every later attempt is refused until HA restarts."""
    # Arrange
    toolkit = _toolkit(tmp_path)

    # Act
    first = toolkit.start_step("stub.touch", device_id="stub-1")
    _await_terminal(toolkit, first["op_id"])

    # Assert: a second attempt is accepted rather than refused as busy.
    second = toolkit.start_step("stub.touch", device_id="stub-1")
    assert second["op_id"] != first["op_id"]
