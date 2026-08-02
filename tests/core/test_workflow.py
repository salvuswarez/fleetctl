"""Tests for workflow parsing, planning, and execution."""

from __future__ import annotations

import threading
from typing import Iterable

import pytest

from fleetctl.core.effects import Capability, Effect
from fleetctl.core.errors import ConfigError, FleetError
from fleetctl.core.inventory.device import Device
from fleetctl.core.observability.audit import AuditKind, ChainedAuditWriter, InMemoryAuditSink, Outcome
from fleetctl.core.operations.registry import OperationStatus
from fleetctl.core.registry import RegisteredStep, Registry
from fleetctl.core.transport.base import CommandRunner
from fleetctl.core.workflow.engine import WorkflowEngine
from fleetctl.core.workflow.plan import PlannedTask, build_plan
from fleetctl.core.workflow.step import StepResult, StepSpec
from fleetctl.core.workflow.workflow import OnError, Target, Workflow

WORKFLOW_YAML = """
name: demo
description: A demo workflow.
steps:
  - id: build
    use: demo.build
    targets: none
  - id: touch
    use: demo.touch
    targets:
      tags: [managed]
    concurrency: 4
    on_error: continue
"""


class _Pack:
    id = "demo"
    platform = "demo"
    capabilities = frozenset({Capability.EXEC})
    probe_priority = 5

    def probe(self, runner: CommandRunner) -> dict[str, str] | None:
        return None

    def steps(self) -> Iterable[RegisteredStep]:
        return [
            RegisteredStep(spec=StepSpec(id="demo.build", summary="build", effect=Effect.MUTATING, scope="transform"), run=_noop, provider="demo"),
            RegisteredStep(
                spec=StepSpec(id="demo.touch", summary="touch", effect=Effect.DESTRUCTIVE, requires=frozenset({Capability.EXEC})),
                run=_noop,
                provider="demo",
            ),
            RegisteredStep(
                spec=StepSpec(id="demo.power", summary="power", effect=Effect.DESTRUCTIVE, requires=frozenset({Capability.POWER})),
                run=_noop,
                provider="demo",
            ),
        ]


def _noop(context: object) -> StepResult:
    return StepResult(summary="ok")


@pytest.fixture
def registry() -> Registry:
    registry = Registry()
    registry.register_device_pack(_Pack())
    return registry


@pytest.fixture
def fleet() -> list[Device]:
    return [
        Device(id="a", type="demo", tags=["managed"]),
        Device(id="b", type="demo", tags=["managed"]),
        Device(id="c", type="demo", tags=["other"]),
        Device(id="d", type="unknown-pack", tags=["managed"]),
    ]


def test_a_workflow_parses_from_yaml() -> None:
    # Act
    workflow = Workflow.from_yaml(WORKFLOW_YAML)

    # Assert
    assert workflow.name == "demo"
    assert [step.id for step in workflow.steps] == ["build", "touch"]
    assert workflow.steps[0].target.is_fleet_level
    assert workflow.steps[1].concurrency == 4
    assert workflow.steps[1].on_error is OnError.CONTINUE


@pytest.mark.parametrize(
    "bad",
    [
        "description: no name\nsteps: [{use: a}]",
        "name: x",
        "name: x\nsteps: []",
        "name: x\nsteps: [{}]",
    ],
)
def test_a_malformed_workflow_is_rejected_with_a_reason(bad: str) -> None:
    # Act / Assert
    with pytest.raises(ConfigError):
        Workflow.from_yaml(bad)


def test_targets_select_by_tag_type_and_id(fleet: list[Device]) -> None:
    # Act / Assert
    assert [d.id for d in Target(tags=("managed",)).select(fleet)] == ["a", "b", "d"]
    assert [d.id for d in Target(tags=("managed",), device_type="demo").select(fleet)] == ["a", "b"]
    assert [d.id for d in Target(ids=("c",)).select(fleet)] == ["c"]
    assert Target(none=True).select(fleet) == []


def test_a_plan_expands_steps_across_targets(registry: Registry, fleet: list[Device]) -> None:
    # Act
    plan = build_plan(Workflow.from_yaml(WORKFLOW_YAML), registry, fleet)

    # Assert
    assert [task.target_id for task in plan.tasks] == ["fleet", "a", "b", "d"]


def test_planning_touches_no_device(registry: Registry, fleet: list[Device]) -> None:
    """A plan must be safe to produce for a fleet that is entirely offline —
    which it is, because capability checks read the pack's declaration."""
    # Act
    plan = build_plan(Workflow.from_yaml(WORKFLOW_YAML), registry, fleet)

    # Assert
    assert plan.tasks  # produced without any transport existing at all


def test_a_device_whose_pack_is_missing_is_blocked_not_dropped(registry: Registry, fleet: list[Device]) -> None:
    """A target silently vanishing is how a fleet-wide run quietly does
    nothing."""
    # Act
    plan = build_plan(Workflow.from_yaml(WORKFLOW_YAML), registry, fleet)

    # Assert
    blocked = plan.blocked
    assert [task.target_id for task in blocked] == ["d"]
    assert "unknown-pack" in blocked[0].blocked


def test_a_pack_lacking_a_capability_blocks_the_task(registry: Registry) -> None:
    # Arrange
    workflow = Workflow.from_yaml("name: p\nsteps:\n  - use: demo.power\n    targets: {tags: [managed]}\n")

    # Act
    plan = build_plan(workflow, registry, [Device(id="a", type="demo", tags=["managed"])])

    # Assert
    assert "power" in plan.blocked[0].blocked


def test_a_device_with_no_type_is_blocked(registry: Registry) -> None:
    # Arrange
    workflow = Workflow.from_yaml("name: p\nsteps:\n  - use: demo.touch\n    targets: {tags: [managed]}\n")

    # Act
    plan = build_plan(workflow, registry, [Device(id="a", tags=["managed"])])

    # Assert
    assert "discovery" in plan.blocked[0].blocked


def test_planning_an_unknown_step_is_an_authoring_error(registry: Registry, fleet: list[Device]) -> None:
    # Arrange
    workflow = Workflow.from_yaml("name: p\nsteps:\n  - use: nope.missing\n")

    # Act / Assert
    with pytest.raises(FleetError):
        build_plan(workflow, registry, fleet)


def test_the_digest_changes_when_the_fleet_changes(registry: Registry, fleet: list[Device]) -> None:
    """So an agent cannot plan against one fleet and execute against another."""
    # Arrange
    workflow = Workflow.from_yaml(WORKFLOW_YAML)

    # Act
    before = build_plan(workflow, registry, fleet).digest()
    after = build_plan(workflow, registry, [*fleet, Device(id="new", type="demo", tags=["managed"])]).digest()

    # Assert
    assert before != after


def test_the_digest_is_stable_for_the_same_plan(registry: Registry, fleet: list[Device]) -> None:
    # Arrange
    workflow = Workflow.from_yaml(WORKFLOW_YAML)

    # Act / Assert
    assert build_plan(workflow, registry, fleet).digest() == build_plan(workflow, registry, fleet).digest()


def test_an_empty_plan_is_reported_rather_than_silently_succeeding(registry: Registry) -> None:
    # Arrange
    workflow = Workflow.from_yaml("name: p\nsteps:\n  - use: demo.touch\n    targets: {tags: [nothing-has-this]}\n")

    # Act
    plan = build_plan(workflow, registry, [Device(id="a", type="demo")])

    # Assert
    assert plan.is_empty


def _engine(statuses: dict[str, OperationStatus], audit: ChainedAuditWriter | None = None) -> tuple[WorkflowEngine, list[str]]:
    ran: list[str] = []
    lock = threading.Lock()

    def _run(task: PlannedTask, op_id: str) -> OperationStatus:
        with lock:
            ran.append(task.target_id)
        return statuses.get(task.target_id, OperationStatus.COMPLETED)

    return WorkflowEngine(_run, audit, actor="cli:test"), ran


def test_the_engine_runs_every_runnable_task(registry: Registry, fleet: list[Device]) -> None:
    # Arrange
    plan = build_plan(Workflow.from_yaml(WORKFLOW_YAML), registry, fleet)
    engine, ran = _engine({})

    # Act
    report = engine.run(plan)

    # Assert
    assert sorted(ran) == ["a", "b", "fleet"]
    assert report.succeeded


def test_a_blocked_task_is_never_attempted(registry: Registry, fleet: list[Device]) -> None:
    # Arrange
    plan = build_plan(Workflow.from_yaml(WORKFLOW_YAML), registry, fleet)
    engine, ran = _engine({})

    # Act
    engine.run(plan)

    # Assert
    assert "d" not in ran


def test_a_skipped_device_is_audited_rather_than_left_silent(registry: Registry, fleet: list[Device]) -> None:
    """A device quietly dropped from a fleet-wide run is exactly the outcome
    nobody notices."""
    # Arrange
    sink = InMemoryAuditSink()
    plan = build_plan(Workflow.from_yaml(WORKFLOW_YAML), registry, fleet)
    engine, _ = _engine({}, ChainedAuditWriter(sink))

    # Act
    engine.run(plan)

    # Assert
    decisions = [event for event in sink.read_all() if event.kind is AuditKind.DECISION]
    assert [event.target for event in decisions] == ["d"]
    assert decisions[0].outcome is Outcome.SKIPPED


def test_the_plan_itself_is_audited(registry: Registry, fleet: list[Device]) -> None:
    # Arrange
    sink = InMemoryAuditSink()
    plan = build_plan(Workflow.from_yaml(WORKFLOW_YAML), registry, fleet)
    engine, _ = _engine({}, ChainedAuditWriter(sink))

    # Act
    engine.run(plan)

    # Assert
    recorded = [event for event in sink.read_all() if event.kind is AuditKind.PLAN]
    assert recorded[0].detail["digest"] == plan.digest()


def test_on_error_continue_lets_the_rest_of_the_fleet_proceed(registry: Registry, fleet: list[Device]) -> None:
    # Arrange
    plan = build_plan(Workflow.from_yaml(WORKFLOW_YAML), registry, fleet)
    engine, ran = _engine({"a": OperationStatus.FAILED})

    # Act
    report = engine.run(plan)

    # Assert
    assert "b" in ran
    assert report.succeeded is False
    assert [outcome.task.target_id for outcome in report.failed] == ["a"]


def test_on_error_stop_halts_the_workflow(registry: Registry) -> None:
    # Arrange
    workflow = Workflow.from_yaml(
        "name: p\nsteps:\n  - id: first\n    use: demo.touch\n    targets: {tags: [m]}\n    on_error: stop\n"
        "  - id: second\n    use: demo.touch\n    targets: {tags: [m]}\n"
    )
    plan = build_plan(workflow, registry, [Device(id="a", type="demo", tags=["m"])])
    engine, ran = _engine({"a": OperationStatus.FAILED})

    # Act
    report = engine.run(plan)

    # Assert
    assert ran == ["a"]
    assert report.stopped_early is True


def test_concurrency_runs_tasks_in_parallel(registry: Registry) -> None:
    # Arrange
    devices = [Device(id=f"d{index}", type="demo", tags=["managed"]) for index in range(4)]
    workflow = Workflow.from_yaml("name: p\nsteps:\n  - use: demo.touch\n    targets: {tags: [managed]}\n    concurrency: 4\n")
    plan = build_plan(workflow, registry, devices)
    barrier = threading.Barrier(4, timeout=5)

    def _run(task: PlannedTask, op_id: str) -> OperationStatus:
        barrier.wait()  # only returns if all four are running at once
        return OperationStatus.COMPLETED

    # Act
    report = WorkflowEngine(_run).run(plan)

    # Assert
    assert report.succeeded


def test_the_run_report_summarises_the_outcome(registry: Registry, fleet: list[Device]) -> None:
    # Arrange
    plan = build_plan(Workflow.from_yaml(WORKFLOW_YAML), registry, fleet)
    engine, _ = _engine({"a": OperationStatus.FAILED})

    # Act
    summary = engine.run(plan).summary()

    # Assert
    assert "2/3" in summary
    assert "with failures" in summary


def test_policy_denial_blocks_a_task_at_plan_time(registry: Registry, fleet: list[Device]) -> None:
    """A denial should be visible in --dry-run, not discovered mid-run."""
    # Arrange
    from fleetctl.core.policy import Policy

    policy = Policy.from_mapping(
        {"protected": [{"match": {"tags": ["managed"]}, "deny": ["demo.touch"], "reason": "held back"}], "actors": {"*": {"allow": ["*"]}}}
    )

    # Act
    plan = build_plan(Workflow.from_yaml(WORKFLOW_YAML), registry, fleet, policy=policy, actor="cli:test")

    # Assert
    assert [task.target_id for task in plan.blocked] == ["a", "b", "d"]
    assert "held back" in plan.blocked[0].blocked


def test_policy_confirmation_marks_a_task_without_blocking_it(registry: Registry, fleet: list[Device]) -> None:
    # Arrange
    from fleetctl.core.policy import Policy

    policy = Policy.from_mapping({"actors": {"mcp:*": {"allow": ["*"], "confirm": ["destructive"]}}})

    # Act
    plan = build_plan(Workflow.from_yaml(WORKFLOW_YAML), registry, fleet, policy=policy, actor="mcp:claude")

    # Assert
    pending = plan.needs_approval
    assert [task.target_id for task in pending] == ["a", "b"]
    assert all(task.runnable for task in pending)


def test_device_count_ignores_blocked_and_fleet_level_tasks(registry: Registry, fleet: list[Device]) -> None:
    # Act
    plan = build_plan(Workflow.from_yaml(WORKFLOW_YAML), registry, fleet)

    # Assert
    assert plan.device_count == 2


def test_the_plan_description_marks_approval_separately_from_blocking(registry: Registry, fleet: list[Device]) -> None:
    # Arrange
    from fleetctl.core.policy import Policy

    policy = Policy.from_mapping({"actors": {"mcp:*": {"allow": ["*"], "confirm": ["destructive"]}}})

    # Act
    described = "\n".join(build_plan(Workflow.from_yaml(WORKFLOW_YAML), registry, fleet, policy=policy, actor="mcp:claude").describe())

    # Assert
    assert "NEEDS APPROVAL" in described
    assert "BLOCKED" in described
