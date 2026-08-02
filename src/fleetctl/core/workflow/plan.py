"""Planning: work out everything that would happen, before anything happens."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..effects import Effect, missing_capabilities
from ..errors import FleetError
from ..inventory.device import Device
from ..policy import Policy, Verdict, permissive
from ..registry import Registry
from .workflow import OnError, Workflow, WorkflowStep


@dataclass(frozen=True, slots=True)
class PlannedTask:
    """One step against one target — the unit that actually runs.

    **PARAMETERS:**
        `step_id` (str): The workflow step's id.  <br>
        `use` (str): The registered step being run.  <br>
        `device` (Device | None): The target, or None for fleet-level work.  <br>
        `effect` (Effect): How much this changes.  <br>
        `params` (Mapping[str, Any]): The step's parameters.  <br>
        `blocked` (str): Why this cannot run, empty when it can.  <br>
        `needs_approval` (str): Why this needs explicit approval, empty when it does not.  <br>
    """

    step_id: str
    use: str
    device: Device | None
    effect: Effect
    params: Mapping[str, Any] = field(default_factory=dict)
    blocked: str = ""
    needs_approval: str = ""

    @property
    def target_id(self) -> str:
        """RETURNS: str: The device id, or ``"fleet"`` for fleet-level work."""
        return self.device.id if self.device else "fleet"

    @property
    def runnable(self) -> bool:
        """RETURNS: bool: Whether this task can run."""
        return not self.blocked


@dataclass(frozen=True, slots=True)
class PlannedStep:
    """One workflow step, expanded across its targets.

    **PARAMETERS:**
        `step` (WorkflowStep): The step as written.  <br>
        `tasks` (tuple[PlannedTask, ...]): One per resolved target.  <br>
    """

    step: WorkflowStep
    tasks: tuple[PlannedTask, ...]

    @property
    def on_error(self) -> OnError:
        """RETURNS: OnError: What a failure in this step does to the workflow."""
        return self.step.on_error


@dataclass(frozen=True, slots=True)
class Plan:
    """Everything a workflow run would do.

    **PARAMETERS:**
        `workflow` (str): Workflow name.  <br>
        `steps` (tuple[PlannedStep, ...]): Steps, in order, each expanded.  <br>
    """

    workflow: str
    steps: tuple[PlannedStep, ...]

    @property
    def tasks(self) -> list[PlannedTask]:
        """RETURNS: list[PlannedTask]: Every task, in execution order."""
        return [task for step in self.steps for task in step.tasks]

    @property
    def blocked(self) -> list[PlannedTask]:
        """RETURNS: list[PlannedTask]: Tasks that cannot run, with reasons."""
        return [task for task in self.tasks if not task.runnable]

    @property
    def needs_approval(self) -> list[PlannedTask]:
        """RETURNS: list[PlannedTask]: Runnable tasks the policy says need explicit approval."""
        return [task for task in self.tasks if task.runnable and task.needs_approval]

    @property
    def device_count(self) -> int:
        """RETURNS: int: How many distinct devices this plan would touch."""
        return len({task.device.id for task in self.tasks if task.device is not None and task.runnable})

    @property
    def is_empty(self) -> bool:
        """RETURNS: bool: Whether the plan resolved to no work at all — usually a target matching nothing."""
        return not self.tasks

    def digest(self) -> str:
        """Hash what this plan would do.

        **RETURNS:**
            `str`: Hex SHA-256 of the plan.  <br>
        """
        payload = [{"step": task.step_id, "use": task.use, "target": task.target_id, "effect": task.effect.value, "params": task.params} for task in self.tasks]
        encoded = json.dumps({"workflow": self.workflow, "tasks": payload}, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def describe(self) -> list[str]:
        """Render the plan for a human.

        **RETURNS:**
            `list[str]`: One line per task, marking anything blocked.  <br>
        """
        lines: list[str] = []
        for planned in self.steps:
            lines.append(f"{planned.step.id} ({planned.step.use})")
            if not planned.tasks:
                lines.append("    - no targets matched")
            for task in planned.tasks:
                marker = "x" if task.blocked else ("?" if task.needs_approval else "-")
                if task.blocked:
                    suffix = f"  BLOCKED: {task.blocked}"
                elif task.needs_approval:
                    suffix = f"  NEEDS APPROVAL: {task.needs_approval}"
                else:
                    suffix = ""
                lines.append(f"    {marker} {task.target_id}  [{task.effect.value}]{suffix}")
        return lines


def build_plan(
    workflow: Workflow,
    registry: Registry,
    devices: Sequence[Device],
    *,
    policy: Policy | None = None,
    actor: str = "cli",
) -> Plan:
    """Expand a workflow into everything it would do.

    **PARAMETERS:**
        `workflow` (Workflow): The workflow to plan.  <br>
        `registry` (Registry): Where step and pack definitions come from.  <br>
        `devices` (Sequence[Device]): The known fleet.  <br>
        `policy` (Policy | None): Rules to evaluate. Defaults to ``None``, meaning permissive.  <br>
        `actor` (str): Who the plan is for; policy decisions depend on it.  <br>

    **RETURNS:**
        `Plan`: The expanded plan. Tasks that cannot run are included and marked, rather than dropped — a target silently vanishing is how a fleet-wide run quietly does nothing.  <br>

    **RAISES:**
        `FleetError`: If a step names something the registry does not know. That is a workflow authoring error, not a runtime condition.  <br>
    """
    policy = policy or permissive()
    planned_steps: list[PlannedStep] = []
    for step in workflow.steps:
        registered = registry.step(step.use)
        spec = registered.spec

        tasks: tuple[PlannedTask, ...]
        targets: list[Device | None] = [None] if step.target.is_fleet_level else list(step.target.select(devices))
        tasks = tuple(_plan_task(step.id, step.use, device, spec, step.params, registry, policy, actor) for device in targets)
        planned_steps.append(PlannedStep(step=step, tasks=tasks))
    return Plan(workflow=workflow.name, steps=tuple(planned_steps))


def _plan_task(
    step_id: str,
    use: str,
    device: Device | None,
    spec: Any,
    params: Mapping[str, Any],
    registry: Registry,
    policy: Policy,
    actor: str,
) -> PlannedTask:
    """Expand one (step, target) pair, applying capability and policy checks."""
    blocked = "" if device is None else _blocked_reason(registry, device, spec.requires)
    approval = ""
    if not blocked:
        decision = policy.check(actor=actor, step_id=use, effect=spec.effect, device=device)
        if decision.verdict is Verdict.DENY:
            blocked = decision.reason
        elif decision.verdict is Verdict.CONFIRM:
            approval = decision.reason
    return PlannedTask(step_id=step_id, use=use, device=device, effect=spec.effect, params=params, blocked=blocked, needs_approval=approval)


def _blocked_reason(registry: Registry, device: Device, required: frozenset[Any]) -> str:
    """RETURNS: str: Why this device cannot run the step, or ``""`` if it can."""
    if not device.is_actionable:
        return f"device is {device.status.value}; approve the debugging prompt on it, then rescan"
    if not device.type:
        return "device has no type; run discovery first"
    try:
        pack = registry.device_pack(device.type)
    except FleetError as exc:
        return str(exc)
    missing = missing_capabilities(frozenset(required), pack.capabilities)
    if missing:
        return f"{device.type} lacks {', '.join(sorted(capability.value for capability in missing))}"
    return ""
