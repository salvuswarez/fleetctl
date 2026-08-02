"""Tests for the agent-facing toolkit.

Weighted toward what an agent must *not* be able to do, because the caller
cannot read a convention and will retry anything that merely looks like a
transient failure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import pytest

from fleetctl.agent.toolkit import ApprovalRequired, PolicyDenied, Toolkit
from fleetctl.cli.bootstrap import build_container
from fleetctl.core.effects import Capability, Effect
from fleetctl.core.errors import FleetError
from fleetctl.core.inventory.device import Device, DeviceStatus
from fleetctl.core.observability.audit import AuditKind, Outcome
from fleetctl.core.registry import RegisteredStep, Registry
from fleetctl.core.transport.base import CommandRunner, Transport
from fleetctl.core.transport.fake import FakeTransport
from fleetctl.core.workflow.step import DeviceStepContext, StepResult, StepSpec

TOUCH = StepSpec(
    id="stub.touch",
    summary="Touch a device.",
    effect=Effect.DESTRUCTIVE,
    requires=frozenset({Capability.EXEC}),
    scope="device",
)
LOOK = StepSpec(id="stub.look", summary="Read something.", effect=Effect.READ, requires=frozenset({Capability.EXEC}), scope="device")

WORKFLOW = "name: tidy\nsteps:\n  - id: touch\n    use: stub.touch\n    targets: {tags: [managed]}\n    on_error: continue\n"


class _StubApps:
    """An application manager for a pack with no real device behind it."""

    def installed_version(self, identifier: str) -> str:
        return ""

    def install(self, package: Path, *, identifier: str = "") -> None:
        return None

    def stop(self, identifier: str) -> None:
        return None


class _StubState:
    platform = "stub"

    def state_root(self, spec: object) -> str:
        return "/state"

    def snapshot(self, spec: object, destination: Path) -> Path:
        return destination

    def restore(self, spec: object, archive: Path) -> None:
        return None


class _StubPack:
    id = "stub"
    platform = "stub"
    capabilities = frozenset({Capability.EXEC})
    probe_priority = 5

    def __init__(self) -> None:
        self.transport = FakeTransport(target="192.168.1.50", responses={"touch": "ok"}, supported=self.capabilities)

    def probe(self, runner: CommandRunner) -> dict[str, str] | None:
        return None

    def transport_for(self, device: Device, settings: Any) -> Transport:
        return self.transport

    def state_manager(self, transport: Transport) -> _StubState:
        return _StubState()

    def app_manager(self, transport: Transport) -> _StubApps:
        return _StubApps()

    def steps(self) -> Iterable[RegisteredStep]:
        return [
            RegisteredStep(spec=TOUCH, run=self._touch, provider=self.id),
            RegisteredStep(spec=LOOK, run=self._touch, provider=self.id),
        ]

    def _touch(self, context: DeviceStepContext) -> StepResult:
        context.transport.exec("touch", effect=Effect.DESTRUCTIVE)
        return StepResult(summary=f"touched {context.device.id}")


def _workspace(tmp_path: Path, policy: str = "", devices: str | None = None) -> Path:
    (tmp_path / "config" / "inventory").mkdir(parents=True)
    (tmp_path / "config" / "workflows").mkdir(parents=True)
    (tmp_path / "config" / "fleet.yml").write_text(policy or "{}\n", encoding="utf-8")
    (tmp_path / "config" / "workflows" / "tidy.yml").write_text(WORKFLOW, encoding="utf-8")
    (tmp_path / "config" / "inventory" / "devices.yml").write_text(
        devices or ("devices:\n  - id: stub-1\n    type: stub\n    address: 192.168.1.50\n    tags: [managed]\n"),
        encoding="utf-8",
    )
    return tmp_path


def _toolkit(tmp_path: Path, policy: str = "", devices: str | None = None, actor: str = "mcp:claude") -> Toolkit:
    root = _workspace(tmp_path, policy, devices)
    registry = Registry()
    registry.register_device_pack(_StubPack())
    container = build_container(config_dir=root / "config", home=root / "home", actor=actor, registry=registry)
    return Toolkit(container=container, actor=actor)


PERMISSIVE = "policy:\n  actors:\n    'mcp:*': {allow: ['*']}\n"
GATED = "policy:\n  actors:\n    'mcp:*': {allow: ['*'], confirm: [destructive]}\n"


def test_reads_need_no_approval(tmp_path: Path) -> None:
    """An agent that cannot look before it acts will act without looking."""
    # Arrange
    toolkit = _toolkit(tmp_path, GATED)

    # Act / Assert
    assert [device["id"] for device in toolkit.list_devices()] == ["stub-1"]
    assert {step["id"] for step in toolkit.list_steps()} == {"stub.touch", "stub.look"}
    assert [workflow["name"] for workflow in toolkit.list_workflows()] == ["tidy"]


def test_the_step_listing_exposes_the_effect_class(tmp_path: Path) -> None:
    """It is what decides whether the agent must ask first, so it must be
    visible to the agent."""
    # Act
    steps = {step["id"]: step for step in _toolkit(tmp_path, GATED).list_steps()}

    # Assert
    assert steps["stub.touch"]["effect"] == "destructive"
    assert steps["stub.look"]["effect"] == "read"


def test_planning_is_always_allowed_and_touches_nothing(tmp_path: Path) -> None:
    # Arrange
    toolkit = _toolkit(tmp_path, GATED)

    # Act
    plan = toolkit.plan_workflow("tidy")

    # Assert
    assert plan["digest"]
    assert plan["device_count"] == 1
    assert [task["target"] for task in plan["tasks"]] == ["stub-1"]


def test_a_plan_reports_what_will_need_approval(tmp_path: Path) -> None:
    # Act
    plan = _toolkit(tmp_path, GATED).plan_workflow("tidy")

    # Assert
    assert [task["target"] for task in plan["needs_approval"]] == ["stub-1"]


def test_running_without_confirming_a_plan_is_refused(tmp_path: Path) -> None:
    """A run that did not confirm a plan is a run nobody reviewed."""
    # Arrange
    toolkit = _toolkit(tmp_path, PERMISSIVE)

    # Act / Assert
    with pytest.raises(FleetError) as caught:
        toolkit.run_workflow("tidy", confirm="not-the-digest", approve=True)
    assert "changed since" in str(caught.value)


def test_a_stale_digest_is_refused_after_the_fleet_changes(tmp_path: Path) -> None:
    """The property that stops an agent planning against one fleet and
    executing against a larger one."""
    # Arrange
    toolkit = _toolkit(tmp_path, PERMISSIVE)
    digest = toolkit.plan_workflow("tidy")["digest"]
    toolkit.container.inventory.save(
        [
            Device(id="stub-1", type="stub", address="192.168.1.50", tags=["managed"]),
            Device(id="stub-2", type="stub", address="192.168.1.51", tags=["managed"]),
        ]
    )

    # Act / Assert
    with pytest.raises(FleetError):
        toolkit.run_workflow("tidy", confirm=digest, approve=True)


def test_a_confirmed_plan_runs(tmp_path: Path) -> None:
    # Arrange
    toolkit = _toolkit(tmp_path, PERMISSIVE)
    digest = toolkit.plan_workflow("tidy")["digest"]

    # Act
    report = toolkit.run_workflow("tidy", confirm=digest)

    # Assert
    assert report["succeeded"] is True
    assert [task["target"] for task in report["tasks"]] == ["stub-1"]


def test_approval_is_required_before_a_destructive_run(tmp_path: Path) -> None:
    # Arrange
    toolkit = _toolkit(tmp_path, GATED)
    digest = toolkit.plan_workflow("tidy")["digest"]

    # Act / Assert
    with pytest.raises(ApprovalRequired) as caught:
        toolkit.run_workflow("tidy", confirm=digest)
    assert caught.value.tasks
    assert "stub-1" in caught.value.tasks[0]


def test_approving_lets_the_same_run_proceed(tmp_path: Path) -> None:
    # Arrange
    toolkit = _toolkit(tmp_path, GATED)
    digest = toolkit.plan_workflow("tidy")["digest"]

    # Act
    report = toolkit.run_workflow("tidy", confirm=digest, approve=True)

    # Assert
    assert report["succeeded"] is True


def test_a_denied_step_cannot_be_approved_away(tmp_path: Path) -> None:
    """Approval answers a question. A denial is not a question."""
    # Arrange
    toolkit = _toolkit(tmp_path, "policy:\n  actors:\n    'mcp:*': {allow: ['*'], deny: ['stub.touch']}\n")

    # Act / Assert
    with pytest.raises(PolicyDenied):
        toolkit.run_step("stub.touch", device_id="stub-1", approve=True)


def test_an_unknown_actor_gets_nothing(tmp_path: Path) -> None:
    # Arrange
    toolkit = _toolkit(tmp_path, "policy:\n  actors:\n    'cli:*': {allow: ['*']}\n")

    # Act / Assert
    with pytest.raises(PolicyDenied):
        toolkit.run_step("stub.look", device_id="stub-1", approve=True)


def test_a_protected_device_is_refused_even_with_approval(tmp_path: Path) -> None:
    # Arrange
    policy = (
        "policy:\n"
        "  protected:\n"
        "    - match: {tags: [managed]}\n"
        "      deny: ['stub.touch']\n"
        "      reason: held back\n"
        "  actors:\n    'mcp:*': {allow: ['*']}\n"
    )
    toolkit = _toolkit(tmp_path, policy)

    # Act / Assert
    with pytest.raises(PolicyDenied) as caught:
        toolkit.run_step("stub.touch", device_id="stub-1", approve=True)
    assert "held back" in str(caught.value)


def test_the_blast_radius_cap_stops_an_oversized_run(tmp_path: Path) -> None:
    # Arrange
    devices = "devices:\n" + "".join(f"  - id: stub-{n}\n    type: stub\n    address: 192.168.1.5{n}\n    tags: [managed]\n" for n in range(4))
    toolkit = _toolkit(tmp_path, "policy:\n  actors:\n    'mcp:*': {allow: ['*'], max_devices: 2}\n", devices)
    digest = toolkit.plan_workflow("tidy")["digest"]

    # Act / Assert
    with pytest.raises(PolicyDenied) as caught:
        toolkit.run_workflow("tidy", confirm=digest, approve=True)
    assert "at most 2" in str(caught.value)


def test_every_refusal_is_audited_with_the_actor(tmp_path: Path) -> None:
    """A policy that silently says no is indistinguishable from a broken tool."""
    # Arrange
    toolkit = _toolkit(tmp_path, "policy:\n  actors:\n    'mcp:*': {allow: ['*'], deny: ['stub.touch']}\n")

    # Act
    with pytest.raises(PolicyDenied):
        toolkit.run_step("stub.touch", device_id="stub-1")

    # Assert
    recorded = [event for event in toolkit.container.audit.records() if event.kind is AuditKind.DECISION]
    assert recorded[-1].outcome is Outcome.DENIED
    assert recorded[-1].actor == "mcp:claude"
    assert recorded[-1].detail["surface"] == "agent"


def test_an_unusable_device_is_refused_with_a_reason(tmp_path: Path) -> None:
    # Arrange
    devices = "devices:\n  - id: stub-1\n    type: stub\n    address: 192.168.1.50\n    tags: [managed]\n    status: unauthorized\n"
    toolkit = _toolkit(tmp_path, PERMISSIVE, devices)

    # Act / Assert
    with pytest.raises(FleetError) as caught:
        toolkit.run_step("stub.look", device_id="stub-1", approve=True)
    assert "unauthorized" in str(caught.value)


def test_an_unknown_workflow_names_what_exists(tmp_path: Path) -> None:
    # Act / Assert
    with pytest.raises(FleetError) as caught:
        _toolkit(tmp_path, PERMISSIVE).plan_workflow("nope")
    assert "tidy" in str(caught.value)


def test_an_unknown_device_is_reported_clearly(tmp_path: Path) -> None:
    # Act / Assert
    with pytest.raises(FleetError) as caught:
        _toolkit(tmp_path, PERMISSIVE).run_step("stub.look", device_id="ghost")
    assert "ghost" in str(caught.value)


def test_a_run_that_matches_no_device_says_so(tmp_path: Path) -> None:
    """Rather than reporting a vacuous success."""
    # Arrange
    devices = "devices:\n  - id: stub-1\n    type: stub\n    address: 192.168.1.50\n    tags: [other]\n"
    toolkit = _toolkit(tmp_path, PERMISSIVE, devices)
    digest = toolkit.plan_workflow("tidy")["digest"]

    # Act / Assert
    with pytest.raises(FleetError) as caught:
        toolkit.run_workflow("tidy", confirm=digest, approve=True)
    assert "no devices" in str(caught.value).lower()


def test_a_successful_run_shows_up_in_the_audit_tail(tmp_path: Path) -> None:
    # Arrange
    toolkit = _toolkit(tmp_path, PERMISSIVE)
    digest = toolkit.plan_workflow("tidy")["digest"]

    # Act
    toolkit.run_workflow("tidy", confirm=digest)

    # Assert
    actions = [event["action"] for event in toolkit.audit_tail(50)]
    assert any("touch" in action for action in actions)
