"""Executing a plan.

The engine owns ordering, concurrency, and what a failure means. It does not
own how a task is turned into a running step — that is the caller's, because
constructing a transport and a context is composition-root work and differs
between the CLI, Home Assistant, and a test.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from ..observability.audit import AuditEvent, AuditKind, ChainedAuditWriter, Outcome
from ..observability.correlation import correlate
from ..operations.registry import OperationStatus
from .plan import Plan, PlannedStep, PlannedTask
from .workflow import OnError

LOGGER = logging.getLogger(__name__)

TaskRunner = Callable[[PlannedTask, str], OperationStatus]


@dataclass(frozen=True, slots=True)
class TaskOutcome:
    """What happened to one task.

    **PARAMETERS:**
        `task` (PlannedTask): The task.  <br>
        `status` (OperationStatus): Its terminal status.  <br>
        `op_id` (str): The operation id it ran under.  <br>
    """

    task: PlannedTask
    status: OperationStatus
    op_id: str


@dataclass(frozen=True, slots=True)
class RunReport:
    """The outcome of a whole workflow run.

    **PARAMETERS:**
        `workflow` (str): Workflow name.  <br>
        `run_id` (str): Correlation id shared by every task in the run.  <br>
        `outcomes` (tuple[TaskOutcome, ...]): One per task attempted.  <br>
        `stopped_early` (bool): Whether a failing step with ``on_error: stop`` cut the run short.  <br>
    """

    workflow: str
    run_id: str
    outcomes: tuple[TaskOutcome, ...] = ()
    stopped_early: bool = False

    @property
    def failed(self) -> list[TaskOutcome]:
        """RETURNS: list[TaskOutcome]: Tasks that did not complete."""
        return [outcome for outcome in self.outcomes if outcome.status is not OperationStatus.COMPLETED]

    @property
    def succeeded(self) -> bool:
        """RETURNS: bool: Whether every attempted task completed and nothing cut the run short."""
        return not self.failed and not self.stopped_early

    def summary(self) -> str:
        """RETURNS: str: One line describing how the run went."""
        total = len(self.outcomes)
        failures = len(self.failed)
        state = "stopped early" if self.stopped_early else ("ok" if not failures else "with failures")
        return f"{self.workflow}: {total - failures}/{total} task(s) completed, {state}"


class WorkflowEngine:
    """Runs a plan, respecting per-step concurrency and error policy.

    **PARAMETERS:**
        `run_task` (TaskRunner): Turns one planned task into a running step and reports its terminal status.  <br>
        `audit` (ChainedAuditWriter | None): Where plan and decision records go. Defaults to ``None``, meaning the run is not audited.  <br>
        `actor` (str): Who initiated the run.  <br>
    """

    def __init__(self, run_task: TaskRunner, audit: ChainedAuditWriter | None = None, *, actor: str = "-") -> None:
        self._run_task = run_task
        self._audit = audit
        self._actor = actor

    def run(self, plan: Plan, *, run_id: str | None = None) -> RunReport:
        """Execute a plan.

        Blocked tasks are recorded and skipped rather than attempted: the plan
        already established they cannot run, and trying anyway would produce a
        failure that says nothing new.

        **PARAMETERS:**
            `plan` (Plan): What to run.  <br>
            `run_id` (str | None): Correlation id for the whole run. Defaults to one derived from the workflow name and the clock.  <br>

        **RETURNS:**
            `RunReport`: What happened.  <br>
        """
        run_id = run_id or f"{plan.workflow}-{int(time.time())}"
        outcomes: list[TaskOutcome] = []
        stopped = False

        with correlate(run_id=run_id, actor=self._actor):
            self._record_plan(plan, run_id)
            for planned in plan.steps:
                step_outcomes = self._run_step(planned, run_id)
                outcomes.extend(step_outcomes)
                if planned.on_error is OnError.STOP and any(outcome.status is not OperationStatus.COMPLETED for outcome in step_outcomes):
                    LOGGER.warning("Stopping %s after %s failed", plan.workflow, planned.step.id)
                    stopped = True
                    break

        return RunReport(workflow=plan.workflow, run_id=run_id, outcomes=tuple(outcomes), stopped_early=stopped)

    def _run_step(self, planned: PlannedStep, run_id: str) -> list[TaskOutcome]:
        runnable = [task for task in planned.tasks if task.runnable]
        for task in planned.tasks:
            if not task.runnable:
                self._record_skip(task, run_id)

        if not runnable:
            return []

        def _execute(task: PlannedTask) -> TaskOutcome:
            op_id = f"{run_id}-{planned.step.id}-{task.target_id}"
            status = self._run_task(task, op_id)
            return TaskOutcome(task=task, status=status, op_id=op_id)

        if planned.step.concurrency <= 1 or len(runnable) == 1:
            return [_execute(task) for task in runnable]

        workers = min(planned.step.concurrency, len(runnable))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"fleetctl-{planned.step.id}") as pool:
            return list(pool.map(_execute, runnable))

    def _record_plan(self, plan: Plan, run_id: str) -> None:
        if self._audit is None:
            return
        self._audit.write(
            AuditEvent.build(
                AuditKind.PLAN,
                f"workflow.plan {plan.workflow}",
                detail={"run_id": run_id, "digest": plan.digest(), "tasks": [task.target_id for task in plan.tasks]},
            )
        )

    def _record_skip(self, task: PlannedTask, run_id: str) -> None:
        """Record a task the plan already ruled out.

        Audited as a decision rather than left silent: a device quietly
        dropped from a fleet-wide run is exactly the outcome nobody notices.
        """
        if self._audit is None:
            return
        self._audit.write(
            AuditEvent.build(
                AuditKind.DECISION,
                f"workflow.skip {task.use}",
                target=task.target_id,
                outcome=Outcome.SKIPPED,
                detail={"run_id": run_id, "reason": task.blocked},
            )
        )
