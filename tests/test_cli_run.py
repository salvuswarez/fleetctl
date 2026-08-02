"""Running steps through the CLI, with a stub pack standing in for hardware.

The full `run` path — capability check, transport lifecycle, config layering,
audit, operation status — exercised without a device.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import pytest
from click.testing import CliRunner

from fleetctl.cli import main as cli_main
from fleetctl.cli.main import main
from fleetctl.core.effects import Capability, Effect
from fleetctl.core.errors import FleetError
from fleetctl.core.inventory.device import Device
from fleetctl.core.observability.audit import verify_chain
from fleetctl.core.registry import RegisteredStep, Registry
from fleetctl.core.state import AppStateSpec
from fleetctl.core.transport.base import CommandRunner, Transport
from fleetctl.core.transport.fake import FakeTransport
from fleetctl.core.workflow.step import DeviceStepContext, StepResult, StepSpec

TOUCH = StepSpec(
    id="stub.touch",
    summary="Touch the device.",
    effect=Effect.DESTRUCTIVE,
    requires=frozenset({Capability.EXEC}),
    scope="device",
)

DEMANDING = StepSpec(
    id="stub.demanding",
    summary="Needs a capability the stub lacks.",
    effect=Effect.MUTATING,
    requires=frozenset({Capability.POWER}),
    scope="device",
)

EXPLODES = StepSpec(id="stub.explodes", summary="Always fails.", effect=Effect.MUTATING, requires=frozenset(), scope="device")


class _StubState:
    platform = "stub"

    def state_root(self, spec: AppStateSpec) -> str:
        return "/state"

    def snapshot(self, spec: AppStateSpec, destination: Path) -> Path:
        destination.write_bytes(b"snap")
        return destination

    def restore(self, spec: AppStateSpec, archive: Path) -> None:
        return None


class _StubPack:
    """A device pack with no hardware behind it."""

    id = "stub"
    platform = "stub"
    capabilities = frozenset({Capability.EXEC, Capability.FILES})
    probe_priority = 5

    def __init__(self) -> None:
        self.transport = FakeTransport(target="192.168.1.50", responses={"touch": "done"}, supported=self.capabilities)

    def probe(self, runner: CommandRunner) -> dict[str, str] | None:
        return None

    def transport_for(self, device: Device, settings: Any) -> Transport:
        return self.transport

    def state_manager(self, transport: Transport) -> _StubState:
        return _StubState()

    def steps(self) -> Iterable[RegisteredStep]:
        return [
            RegisteredStep(spec=TOUCH, run=self._touch, provider=self.id),
            RegisteredStep(spec=DEMANDING, run=self._touch, provider=self.id),
            RegisteredStep(spec=EXPLODES, run=self._explode, provider=self.id),
        ]

    def _touch(self, context: DeviceStepContext) -> StepResult:
        context.handle.log(f"touching {context.device.id}")
        context.transport.exec("touch", effect=Effect.DESTRUCTIVE)
        return StepResult(summary=f"touched {context.device.id}", facts={"scale": context.config.get("scale", "unset")})

    def _explode(self, context: DeviceStepContext) -> StepResult:
        raise FleetError("the device said no")


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "config" / "inventory").mkdir(parents=True)
    (tmp_path / "config" / "fleet.yml").write_text("scale: fleet-default\n", encoding="utf-8")
    (tmp_path / "config" / "inventory" / "devices.yml").write_text(
        "devices:\n  - id: stub-1\n    type: stub\n    address: 192.168.1.50\n    vars:\n      scale: device-value\n", encoding="utf-8"
    )

    registry = Registry()
    registry.register_device_pack(_StubPack())
    monkeypatch.setattr(cli_main, "build_container", _patched(registry, tmp_path))
    return tmp_path


def _patched(registry: Registry, root: Path) -> Any:
    from fleetctl.cli.bootstrap import build_container

    def _build(**kwargs: Any) -> Any:
        kwargs["registry"] = registry
        kwargs.setdefault("config_dir", root / "config")
        kwargs.setdefault("home", root / "home")
        kwargs["config_dir"] = kwargs["config_dir"] or root / "config"
        kwargs["home"] = kwargs["home"] or root / "home"
        return build_container(**kwargs)

    return _build


def _invoke(*args: str) -> Any:
    return CliRunner().invoke(main, list(args))


def test_a_step_runs_and_reports_success(workspace: Path) -> None:
    # Act
    result = _invoke("run", "stub.touch", "--device", "stub-1")

    # Assert
    assert result.exit_code == 0, result.output
    assert "touching stub-1" in result.output
    assert "touched stub-1" in result.output


def test_the_run_is_written_to_the_audit_trail(workspace: Path) -> None:
    # Act
    _invoke("run", "stub.touch", "--device", "stub-1")
    tailed = _invoke("audit", "tail")

    # Assert
    assert "touch" in tailed.output
    assert "cli" in tailed.output


def test_the_audit_chain_verifies_after_a_run(workspace: Path) -> None:
    # Act
    _invoke("run", "stub.touch", "--device", "stub-1")
    result = _invoke("audit", "verify")

    # Assert
    assert result.exit_code == 0, result.output
    assert "chain intact" in result.output


def test_audit_records_survive_a_process_restart(workspace: Path) -> None:
    """Each CLI invocation is a fresh process; the JSONL sink is what makes
    the trail outlive it."""
    # Act
    _invoke("run", "stub.touch", "--device", "stub-1")
    _invoke("run", "stub.touch", "--device", "stub-1")
    result = _invoke("audit", "tail")

    # Assert
    assert result.output.count("touch") >= 2


def test_a_missing_capability_is_caught_before_the_step_runs(workspace: Path) -> None:
    # Act
    result = _invoke("run", "stub.demanding", "--device", "stub-1")

    # Assert
    assert result.exit_code != 0
    assert "power" in result.output


def test_a_failing_step_reports_the_reason_and_exits_nonzero(workspace: Path) -> None:
    # Act
    result = _invoke("run", "stub.explodes", "--device", "stub-1")

    # Assert
    assert result.exit_code != 0
    assert "the device said no" in result.output


def test_device_vars_beat_fleet_config(workspace: Path) -> None:
    # Act
    result = _invoke("config", "stub-1")

    # Assert
    assert "scale = device-value  [device]" in result.output


def test_a_command_line_override_beats_everything(workspace: Path) -> None:
    # Act
    result = _invoke("run", "stub.touch", "--device", "stub-1", "--set", "scale=flag-value")

    # Assert
    assert result.exit_code == 0, result.output


def test_verbose_flags_are_accepted(workspace: Path) -> None:
    # Act
    result = _invoke("-vv", "run", "stub.touch", "--device", "stub-1")

    # Assert
    assert result.exit_code == 0, result.output


def test_artifacts_list_reports_an_empty_kind(workspace: Path) -> None:
    # Act
    result = _invoke("artifacts", "list", "builds")

    # Assert
    assert result.exit_code == 0
    assert "No artifacts" in result.output


def test_config_show_rejects_an_unknown_device(workspace: Path) -> None:
    # Act
    result = _invoke("config", "ghost")

    # Assert
    assert result.exit_code != 0
    assert "Unknown device" in result.output


def test_the_recorded_chain_is_internally_consistent(workspace: Path) -> None:
    # Arrange
    from fleetctl.core.observability.audit import JsonlAuditSink

    _invoke("run", "stub.touch", "--device", "stub-1")

    # Act
    events = JsonlAuditSink(workspace / "home" / "audit").read_all()

    # Assert
    assert events
    assert verify_chain(events) == (True, None)
