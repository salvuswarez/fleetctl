"""Tests for pack discovery and the CLI that is generated from it."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import pytest
from click.testing import CliRunner

from fleetctl.apps.kodi.pack import KodiApp
from fleetctl.cli.bootstrap import build_container
from fleetctl.cli.main import main
from fleetctl.core.effects import Capability, Effect
from fleetctl.core.errors import FleetError
from fleetctl.core.registry import RegisteredStep, Registry, discover
from fleetctl.core.transport.base import CommandRunner
from fleetctl.core.workflow.step import StepResult, StepSpec
from fleetctl.packs.firetv.pack import FireTvPack


class _StubPack:
    """A minimal device pack, for registration tests."""

    def __init__(self, pack_id: str = "stub", step_id: str = "stub.noop", priority: int = 50) -> None:
        self.id = pack_id
        self.platform = "stub"
        self.capabilities = frozenset({Capability.EXEC})
        self.probe_priority = priority
        self._step_id = step_id

    def probe(self, runner: CommandRunner) -> dict[str, str] | None:
        return None

    def steps(self) -> Iterable[RegisteredStep]:
        spec = StepSpec(id=self._step_id, summary="noop", effect=Effect.READ)
        return [RegisteredStep(spec=spec, run=lambda context: StepResult(summary="ok"), provider=self.id)]


def test_a_registered_pack_exposes_its_steps() -> None:
    # Arrange
    registry = Registry()

    # Act
    registry.register_device_pack(_StubPack())

    # Assert
    assert registry.device_pack("stub").id == "stub"
    assert registry.step("stub.noop").provider == "stub"


def test_registering_the_same_pack_twice_is_rejected() -> None:
    # Arrange
    registry = Registry()
    registry.register_device_pack(_StubPack())

    # Act / Assert
    with pytest.raises(FleetError):
        registry.register_device_pack(_StubPack())


def test_two_packs_cannot_claim_the_same_step_id() -> None:
    """A silent overwrite would let one pack shadow another's steps."""
    # Arrange
    registry = Registry()
    registry.register_device_pack(_StubPack(pack_id="one", step_id="shared.step"))

    # Act / Assert
    with pytest.raises(FleetError) as caught:
        registry.register_device_pack(_StubPack(pack_id="two", step_id="shared.step"))
    assert "one" in str(caught.value)


def test_an_unknown_pack_names_what_is_available() -> None:
    # Arrange
    registry = Registry()
    registry.register_device_pack(_StubPack())

    # Act / Assert
    with pytest.raises(FleetError) as caught:
        registry.device_pack("nope")
    assert "stub" in str(caught.value)


def test_packs_are_ordered_for_probing() -> None:
    """Probe order decides which pack claims a host, so it must be explicit."""
    # Arrange
    registry = Registry()
    registry.register_device_pack(_StubPack(pack_id="late", step_id="late.noop", priority=99))
    registry.register_device_pack(_StubPack(pack_id="early", step_id="early.noop", priority=1))

    # Act
    ordered = [pack.id for pack in registry.device_packs()]

    # Assert
    assert ordered == ["early", "late"]


def test_a_broken_pack_is_skipped_rather_than_breaking_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    """One third-party pack failing to import must not stop you managing the
    devices you can still reach."""

    # Arrange
    class _Entry:
        name = "broken"

        def load(self) -> Any:
            raise ImportError("its optional dependency is missing")

    monkeypatch.setattr("fleetctl.core.registry.metadata.entry_points", lambda group: [_Entry()] if group == "fleetctl.packs" else [])

    # Act
    registry = discover(Registry())

    # Assert
    assert registry.device_packs() == []


def test_the_shipped_packs_are_discovered_through_entry_points() -> None:
    """The registration path a third-party pack would use, exercised on our
    own packs rather than bypassed in tests."""
    # Act
    registry = discover()

    # Assert
    assert registry.device_pack("firetv").id == "firetv"
    assert registry.app_pack("kodi").id == "kodi"
    assert {step.spec.id for step in registry.steps()} >= {"firetv.maintain", "kodi.capture", "kodi.build", "kodi.deploy"}


def test_the_kodi_app_builds_its_transform_chain_from_the_shipped_recipe() -> None:
    # Act
    transforms = KodiApp().transforms

    # Assert
    assert [transform.name for transform in transforms] == ["prune_addons", "apply_settings"]


def test_the_firetv_pack_registers_exactly_its_maintain_step() -> None:
    # Act
    steps = list(FireTvPack().steps())

    # Assert
    assert [step.spec.id for step in steps] == ["firetv.maintain"]
    assert steps[0].spec.effect is Effect.DESTRUCTIVE


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "config" / "inventory").mkdir(parents=True)
    (tmp_path / "config" / "fleet.yml").write_text("observability:\n  audit_dir: audit\n", encoding="utf-8")
    (tmp_path / "config" / "inventory" / "devices.yml").write_text(
        "devices:\n  - id: stick-1\n    type: firetv\n    address: 192.168.1.50\n    tags: [kodi]\n", encoding="utf-8"
    )
    return tmp_path


def _invoke(workspace: Path, *args: str) -> Any:
    return CliRunner().invoke(main, ["--config-dir", str(workspace / "config"), "--home", str(workspace / "home"), *args])


def test_steps_command_lists_every_registered_step(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "steps")

    # Assert
    assert result.exit_code == 0
    assert "kodi.deploy" in result.output
    assert "firetv.maintain" in result.output


def test_steps_command_shows_the_effect_class(workspace: Path) -> None:
    """An operator should be able to see what is destructive before running it."""
    # Act
    result = _invoke(workspace, "steps")

    # Assert
    assert "destructive" in result.output


def test_packs_command_lists_installed_packs(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "packs")

    # Assert
    assert result.exit_code == 0
    assert "firetv" in result.output


def test_devices_list_reads_the_inventory(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "devices", "list")

    # Assert
    assert result.exit_code == 0
    assert "stick-1" in result.output
    assert "192.168.1.50" in result.output


def test_devices_list_is_empty_without_an_inventory(tmp_path: Path) -> None:
    # Act
    result = _invoke(tmp_path, "devices", "list")

    # Assert
    assert result.exit_code == 0
    assert "No devices" in result.output


def test_running_an_unknown_step_names_what_exists(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "run", "nope.nothing")

    # Assert
    assert result.exit_code != 0
    assert "kodi.capture" in result.output


def test_a_device_step_without_a_device_is_a_usage_error(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "run", "kodi.deploy")

    # Assert
    assert result.exit_code != 0
    assert "--device" in result.output


def test_running_against_an_unknown_device_fails_clearly(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "run", "kodi.deploy", "--device", "ghost")

    # Assert
    assert result.exit_code != 0
    assert "Unknown device: ghost" in result.output


def test_config_show_explains_where_each_value_came_from(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "config", "stick-1")

    # Assert
    assert result.exit_code == 0
    assert "[fleet]" in result.output


def test_set_requires_key_equals_value(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "run", "kodi.build", "--set", "malformed")

    # Assert
    assert result.exit_code != 0
    assert "KEY=VALUE" in result.output


def test_audit_verify_reports_an_empty_trail(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "audit", "verify")

    # Assert
    assert result.exit_code == 0
    assert "No audit records" in result.output


def test_the_container_resolves_secret_references(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fleet.yml holds pointers; values arrive from the environment."""
    # Arrange
    monkeypatch.setenv("FLEETCTL_TEST_TOKEN", "hunter2")
    (workspace / "config" / "fleet.yml").write_text("artifacts:\n  token: !ref env:FLEETCTL_TEST_TOKEN\n", encoding="utf-8")

    # Act
    container = build_container(config_dir=workspace / "config", home=workspace / "home")

    # Assert
    assert container.config["artifacts"]["token"].reveal() == "hunter2"


def test_a_build_step_runs_without_any_device(workspace: Path) -> None:
    """A fleet-scoped step must not need a transport. It fails here only
    because there is nothing captured yet, not because of a device."""
    # Act
    result = _invoke(workspace, "run", "kodi.build")

    # Assert
    assert result.exit_code != 0
    assert "captures" in result.output.lower()


def test_workflow_list_includes_the_shipped_workflow(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "workflow", "list")

    # Assert
    assert result.exit_code == 0
    assert "kodi-refresh" in result.output


def test_workflow_plan_shows_targets_and_a_digest(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "workflow", "plan", "kodi-refresh")

    # Assert
    assert result.exit_code == 0
    assert "stick-1" in result.output
    assert "digest:" in result.output


def test_a_dry_run_executes_nothing(workspace: Path) -> None:
    """The S3 exit criterion: a plan you can read before anything happens."""
    # Act
    result = _invoke(workspace, "workflow", "run", "kodi-refresh", "--dry-run")

    # Assert
    assert result.exit_code == 0
    assert "nothing was executed" in result.output
    assert (workspace / "home" / "audit").exists() is False


def test_an_unknown_workflow_names_what_exists(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "workflow", "plan", "nope")

    # Assert
    assert result.exit_code != 0
    assert "kodi-refresh" in result.output


def test_a_stale_plan_digest_is_refused(workspace: Path) -> None:
    """So a run cannot execute against a fleet that changed after planning."""
    # Act
    result = _invoke(workspace, "workflow", "run", "kodi-refresh", "--confirm", "0" * 64)

    # Assert
    assert result.exit_code != 0
    assert "changed since" in result.output


def test_a_user_workflow_shadows_a_shipped_one(workspace: Path) -> None:
    """Shipping a workflow is a starting point, not a constraint."""
    # Arrange
    (workspace / "config" / "workflows").mkdir()
    (workspace / "config" / "workflows" / "kodi-refresh.yml").write_text(
        "name: kodi-refresh\ndescription: mine\nsteps:\n  - use: kodi.build\n    targets: none\n", encoding="utf-8"
    )

    # Act
    result = _invoke(workspace, "workflow", "plan", "kodi-refresh")

    # Assert
    assert result.exit_code == 0
    assert "maintain" not in result.output


def _with_policy(workspace: Path, policy_yaml: str) -> None:
    (workspace / "config" / "fleet.yml").write_text(f"observability:\n  audit_dir: audit\npolicy:\n{policy_yaml}", encoding="utf-8")


def test_a_protected_device_is_refused_and_the_denial_is_audited(workspace: Path) -> None:
    # Arrange
    _with_policy(
        workspace,
        "  protected:\n    - match: {tags: [kodi]}\n      deny: ['kodi.deploy']\n      reason: held back for now\n  actors:\n    'cli:*': {allow: ['*']}\n",
    )

    # Act
    result = _invoke(workspace, "run", "kodi.deploy", "--device", "stick-1")
    tailed = _invoke(workspace, "audit", "tail")

    # Assert
    assert result.exit_code != 0
    assert "held back for now" in result.output
    assert "policy.deny" in tailed.output


def test_an_unknown_actor_is_denied_when_a_policy_exists(workspace: Path) -> None:
    # Arrange
    _with_policy(workspace, "  actors:\n    'mcp:*': {allow: ['*']}\n")

    # Act
    result = _invoke(workspace, "run", "kodi.build")

    # Assert
    assert result.exit_code != 0
    assert "No policy rule covers actor" in result.output


def test_a_workflow_needing_approval_refuses_without_the_flag(workspace: Path) -> None:
    # Arrange
    _with_policy(workspace, "  actors:\n    'cli:*': {allow: ['*'], confirm: ['destructive']}\n")

    # Act
    result = _invoke(workspace, "workflow", "run", "kodi-refresh")

    # Assert
    assert result.exit_code != 0
    assert "Approval required" in result.output


def test_the_plan_shows_what_needs_approval(workspace: Path) -> None:
    # Arrange
    _with_policy(workspace, "  actors:\n    'cli:*': {allow: ['*'], confirm: ['destructive']}\n")

    # Act
    result = _invoke(workspace, "workflow", "plan", "kodi-refresh")

    # Assert
    assert "NEEDS APPROVAL" in result.output


def test_a_blast_radius_cap_refuses_an_oversized_run(workspace: Path) -> None:
    # Arrange
    (workspace / "config" / "inventory" / "devices.yml").write_text(
        "devices:\n" + "".join(f"  - id: stick-{n}\n    type: firetv\n    address: 192.168.1.5{n}\n    tags: [kodi]\n" for n in range(4)),
        encoding="utf-8",
    )
    _with_policy(workspace, "  actors:\n    'cli:*': {allow: ['*'], max_devices: 2}\n")

    # Act
    result = _invoke(workspace, "workflow", "run", "kodi-refresh")

    # Assert
    assert result.exit_code != 0
    assert "at most 2" in result.output


def test_a_denial_records_who_was_refused(workspace: Path) -> None:
    """A record that cannot say who was refused is half a record."""
    # Arrange
    _with_policy(workspace, "  actors:\n    'cli:*': {allow: ['*'], deny: ['kodi.deploy']}\n")

    # Act
    _invoke(workspace, "run", "kodi.deploy", "--device", "stick-1")
    from fleetctl.core.observability.audit import JsonlAuditSink

    events = JsonlAuditSink(workspace / "home" / "audit").read_all()

    # Assert
    assert events
    assert events[-1].actor.startswith("cli:")
    assert events[-1].target == "stick-1"
