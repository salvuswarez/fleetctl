"""Forgetting a device that has work running.

The device you most want to remove is the one holding a stuck operation, so
a refusal there is the wrong answer. The operation is cancelled first, then
the record goes: an id the inventory no longer knows must not still be
receiving instructions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from fleetctl.agent.toolkit import Toolkit
from fleetctl.cli.bootstrap import build_container
from fleetctl.core.effects import Capability, Effect
from fleetctl.core.inventory.device import Device
from fleetctl.core.operations.registry import OperationStatus
from fleetctl.core.registry import RegisteredStep, Registry
from fleetctl.core.transport.base import CommandRunner, Transport
from fleetctl.core.workflow.step import DeviceStepContext, StepResult, StepSpec

TOUCH = StepSpec(id="stub.touch", summary="Touch it.", effect=Effect.READ, requires=frozenset({Capability.EXEC}), scope="device")
DEVICES = "devices:\n  - id: stub-1\n    type: stub\n    address: 192.168.1.50\n    tags: [kodi]\n"


class _StubPack:
    id = "stub"
    platform = "stub"
    capabilities = frozenset({Capability.EXEC})
    probe_priority = 5
    app_profiles: dict[str, str] = {}

    def probe(self, runner: CommandRunner) -> dict[str, str] | None:
        return None

    def transport_for(self, device: Device, settings: Any) -> Transport:
        raise AssertionError("no test here starts real work")

    def steps(self) -> Iterable[RegisteredStep]:
        return [RegisteredStep(spec=TOUCH, run=self._touch, provider=self.id)]

    def _touch(self, context: DeviceStepContext) -> StepResult:
        raise AssertionError("no test here starts real work")


def _toolkit(tmp_path: Path) -> Toolkit:
    (tmp_path / "config" / "inventory").mkdir(parents=True)
    (tmp_path / "config" / "fleet.yml").write_text("{}\n", encoding="utf-8")
    (tmp_path / "config" / "inventory" / "devices.yml").write_text(DEVICES, encoding="utf-8")

    registry = Registry()
    registry.register_device_pack(_StubPack())
    container = build_container(config_dir=tmp_path / "config", home=tmp_path / "home", actor="ha:test", registry=registry)
    return Toolkit(container=container, actor="ha:test")


def _run_something_against(toolkit: Toolkit, device_id: str) -> str:
    """RETURNS: str: Id of an operation left RUNNING against `device_id`."""
    op_id = toolkit.container.operations.new_id("ha:test-stub.touch")
    toolkit.container.operations.start(op_id, "stub.touch", target=device_id)
    return op_id


def test_forgetting_a_busy_device_is_allowed(tmp_path: Path) -> None:
    """It was refused before, which made the button look broken on exactly the
    device the user was trying to get rid of."""
    # Arrange
    toolkit = _toolkit(tmp_path)
    _run_something_against(toolkit, "stub-1")

    # Act
    result = toolkit.forget_device("stub-1")

    # Assert
    assert result["removed"] is True
    assert toolkit.container.inventory.get("stub-1") is None


def test_forgetting_a_busy_device_cancels_its_operation_first(tmp_path: Path) -> None:
    """Cooperative cancellation: the work unwinds at its next step boundary
    rather than being abandoned mid-transfer."""
    # Arrange
    toolkit = _toolkit(tmp_path)
    op_id = _run_something_against(toolkit, "stub-1")

    # Act
    result = toolkit.forget_device("stub-1")

    # Assert
    assert result["cancelled"] == [op_id]
    assert toolkit.container.operations.is_cancel_requested(op_id) is True


def test_forgetting_an_idle_device_cancels_nothing(tmp_path: Path) -> None:
    # Arrange
    toolkit = _toolkit(tmp_path)

    # Act
    result = toolkit.forget_device("stub-1")

    # Assert
    assert result["cancelled"] == []
    assert result["tags"] == ["kodi"]


def test_a_finished_operation_does_not_count_as_busy(tmp_path: Path) -> None:
    # Arrange
    toolkit = _toolkit(tmp_path)
    op_id = _run_something_against(toolkit, "stub-1")
    toolkit.container.operations.finish(op_id, OperationStatus.COMPLETED, "done")

    # Act
    result = toolkit.forget_device("stub-1")

    # Assert
    assert result["cancelled"] == []
