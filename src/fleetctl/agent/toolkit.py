"""What an agent may ask fleetctl to do, and on what terms."""

from __future__ import annotations

import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Mapping

from ..cli.bootstrap import Container
from ..core.errors import FleetError
from ..core.observability.audit import AuditEvent, AuditKind, Outcome
from ..core.observability.correlation import correlate
from ..core.operations.registry import OperationHandle, OperationStatus
from ..core.policy import Verdict
from ..core.registry import RegisteredStep
from ..core.workflow.engine import WorkflowEngine
from ..core.workflow.plan import Plan, PlannedTask, build_plan

LOGGER = logging.getLogger(__name__)


class ApprovalRequired(FleetError):
    """A step needs explicit approval before it may run.

    **PARAMETERS:**
        `message` (str): What needs approving and why.  <br>
        `tasks` (tuple[str, ...]): Human-readable descriptions of what would run.  <br>
    """

    def __init__(self, message: str, tasks: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.tasks = tasks


class PolicyDenied(FleetError):
    """The policy layer refused outright. Not answerable by approving."""


@dataclass(frozen=True, slots=True)
class Toolkit:
    """The operations an agent can perform, with policy applied to each.

    **PARAMETERS:**
        `container` (Container): Resolved dependencies, including the policy.  <br>
        `actor` (str): Who is calling, e.g. ``mcp:claude``. Matched against policy rules and recorded on every audit event.  <br>
    """

    container: Container
    actor: str = "mcp:agent"

    # -- Reads -------------------------------------------------------------

    def list_devices(self) -> list[dict[str, Any]]:
        """RETURNS: list[dict[str, Any]]: The full inventory record for every known device, including ones flagged unusable."""
        return [
            {
                "id": device.id,
                "type": device.type or None,
                "address": device.address or None,
                "mac": device.mac or None,
                "name": device.name or None,
                "model": device.model or None,
                "serial": device.serial or None,
                "os_version": device.os_version or None,
                "tags": list(device.tags),
                "status": device.status.value,
                "actionable": device.is_actionable,
                "vars": dict(device.vars),
            }
            for device in self.container.inventory.list()
        ]

    def device_power(self, device_id: str) -> dict[str, Any]:
        """Read whether one device is awake, cheaply and without recording an operation.

        Deliberately not a step. This is meant to be polled on a short
        interval, and a polled read routed through `run_step` becomes an
        uncancellable RUNNING operation per poll, burying real work in the
        timeline — a mistake this project has already made once.

        Never raises for an unreachable device: something polling this needs
        "not answering" as a value, not an exception. A device that is off,
        unauthorized, or claimed by a pack with no power support all report
        `reachable: false` with `state: ""`.

        **PARAMETERS:**
            `device_id` (str): Inventory id.  <br>

        **RETURNS:**
            `dict[str, Any]`: `device`, `reachable`, `state`, and `awake`. `awake` is only ever true on a positive reading, so an unreachable device never looks awake.  <br>
        """
        answer: dict[str, Any] = {"device": device_id, "reachable": False, "state": "", "awake": False}

        device = self.container.inventory.get(device_id)
        if device is None or not device.type:
            return answer

        try:
            pack = self.container.registry.device_pack(device.type)
        except FleetError:
            return answer

        # Optional on the pack protocol, read the way the composition root
        # reads `transport_for` and `app_profiles`: a pack that cannot answer
        # for power simply does not offer this.
        read = getattr(pack, "power_state", None)
        if read is None:
            return answer

        transport = None
        try:
            transport = self.container.transport_for(device)
            state = str(read(transport) or "")
        except (FleetError, OSError):
            LOGGER.debug("Could not read power state for %s", device_id, exc_info=True)
            return answer
        finally:
            if transport is not None:
                with suppress(Exception):
                    transport.close()

        return {"device": device_id, "reachable": bool(state), "state": state, "awake": state == "awake"}

    def list_steps(self) -> list[dict[str, Any]]:
        """RETURNS: list[dict[str, Any]]: Registered steps, with the effect class that decides how they are gated."""
        return [
            {
                "id": step.spec.id,
                "summary": step.spec.summary,
                "effect": step.spec.effect.value,
                "scope": step.spec.scope,
                "provider": step.provider,
                "requires": sorted(capability.value for capability in step.spec.requires),
            }
            for step in self.container.registry.steps()
        ]

    def list_workflows(self) -> list[dict[str, Any]]:
        """RETURNS: list[dict[str, Any]]: Available workflows and their steps."""
        return [
            {
                "name": workflow.name,
                "description": workflow.description.strip(),
                "steps": [{"id": step.id, "use": step.use} for step in workflow.steps],
            }
            for workflow in sorted(self.container.workflows().values(), key=lambda item: item.name)
        ]

    def list_operations(self) -> list[dict[str, Any]]:
        """RETURNS: list[dict[str, Any]]: Snapshots of every tracked operation in this process."""
        return list(self.container.operations.all_snapshots().values())

    def get_operation(self, op_id: str) -> dict[str, Any] | None:
        """RETURNS: dict[str, Any] | None: One operation's snapshot, or None if it is unknown or has aged out."""
        operation = self.container.operations.get(op_id)
        return operation.snapshot() if operation else None

    def list_artifacts(self, kind: str) -> list[dict[str, Any]]:
        """List stored artifacts of one kind, newest first.

        **PARAMETERS:**
            `kind` (str): Artifact kind, e.g. ``builds`` or ``captures``.  <br>

        **RETURNS:**
            `list[dict[str, Any]]`: Each artifact's reference, size, age, and recorded metadata. Empty when the store holds none of that kind.  <br>
        """
        return [
            {
                "ref": info.ref.wire,
                "kind": info.ref.kind,
                "name": info.ref.name,
                "size": info.size,
                "created_at": info.created_at,
                "meta": dict(info.meta),
            }
            for info in self.container.artifacts.list(kind)
        ]

    def audit_tail(self, count: int = 20) -> list[dict[str, Any]]:
        """RETURNS: list[dict[str, Any]]: The most recent audit records, already redacted."""
        return [event.to_dict() for event in self.container.audit.records()[-count:]]

    # -- Planning ----------------------------------------------------------

    def plan_workflow(self, name: str) -> dict[str, Any]:
        """Show everything a workflow would do, without doing any of it.

        **PARAMETERS:**
            `name` (str): Workflow name.  <br>

        **RETURNS:**
            `dict[str, Any]`: The plan, its digest, and what is blocked or needs approval.  <br>

        **RAISES:**
            `FleetError`: If no such workflow exists.  <br>
        """
        return _describe(self._plan(name))

    # -- Changes -----------------------------------------------------------

    def run_workflow(self, name: str, *, confirm: str, approve: bool = False) -> dict[str, Any]:
        """Run a workflow whose plan the caller has already reviewed.

        **PARAMETERS:**
            `name` (str): Workflow name.  <br>
            `confirm` (str): Digest from `plan_workflow`. Required — a run that did not confirm a plan is a run nobody reviewed.  <br>
            `approve` (bool): Whether the caller approves the tasks the policy flagged.  <br>

        **RETURNS:**
            `dict[str, Any]`: What ran and how it went.  <br>

        **RAISES:**
            `FleetError`: If the plan changed since it was shown, or nothing would run.  <br>
            `ApprovalRequired`: If tasks need approval and `approve` is false.  <br>
            `PolicyDenied`: If the blast-radius cap would be exceeded.  <br>
        """
        plan = self._plan(name)

        if confirm != plan.digest():
            raise FleetError(f"The fleet changed since that plan was made. Call plan_workflow again and confirm {plan.digest()!r}.")
        if plan.is_empty:
            raise FleetError(f"Workflow {name!r} matched no devices; nothing to run.")

        radius = self.container.policy.check_blast_radius(actor=self.actor, device_count=plan.device_count)
        if radius.denied:
            self._record_denial(name, "fleet", radius.reason)
            raise PolicyDenied(radius.reason)

        pending = plan.needs_approval
        if pending and not approve:
            raise ApprovalRequired(
                f"{len(pending)} task(s) need approval before {name!r} can run.",
                tuple(f"{task.step_id} on {task.target_id}: {task.needs_approval}" for task in pending),
            )

        return self._execute(plan)

    def run_step(self, step_id: str, *, device_id: str | None = None, params: Mapping[str, Any] | None = None, approve: bool = False) -> dict[str, Any]:
        """Run a single registered step.

        **PARAMETERS:**
            `step_id` (str): Which step, from `list_steps`.  <br>
            `device_id` (str | None): Target device for a device-scoped step.  <br>
            `params` (Mapping[str, Any] | None): Step parameters.  <br>
            `approve` (bool): Whether the caller approves, when the policy asks.  <br>

        **RETURNS:**
            `dict[str, Any]`: The operation's outcome.  <br>

        **RAISES:**
            `FleetError`: If the step or device is unknown.  <br>
            `ApprovalRequired`: If the policy asks and `approve` is false.  <br>
            `PolicyDenied`: If the policy refuses outright.  <br>
        """
        step, op_id = self._authorize(step_id, device_id, approve=approve)
        with correlate(actor=self.actor):
            status = self._invoke(step, device_id, dict(params or {}), op_id)
        operation = self.container.operations.get(op_id)
        return {
            "op_id": op_id,
            "step": step_id,
            "target": device_id or "fleet",
            "status": status.value,
            "result": operation.result if operation else None,
            "facts": dict(operation.facts) if operation else {},
            "logs": [entry["message"] for entry in operation.logs] if operation else [],
        }

    def cancel_operation(self, op_id: str) -> dict[str, Any]:
        """Ask a running operation to stop.

        The operation is not marked cancelled here: the work observes the
        request at its next step boundary and unwinds itself, so a device is
        never left mid-transfer.

        **PARAMETERS:**
            `op_id` (str): Which operation, from `list_operations`.  <br>

        **RETURNS:**
            `dict[str, Any]`: Whether the request was accepted, and the operation's status.  <br>
        """
        requested = self.container.operations.request_cancel(op_id)
        operation = self.container.operations.get(op_id)
        with correlate(actor=self.actor, op_id=op_id):
            self.container.audit.write(
                AuditEvent.build(
                    AuditKind.DECISION,
                    f"operation.cancel {op_id}",
                    target=operation.target if operation else "unknown",
                    outcome=Outcome.OK if requested else Outcome.SKIPPED,
                    detail={"surface": "agent", "step_id": operation.step_id if operation else None},
                )
            )
        return {
            "op_id": op_id,
            "requested": requested,
            "status": operation.status.value if operation else None,
            "reason": None if requested else ("Unknown operation" if operation is None else f"Already {operation.status.value}"),
        }

    def rerun_operation(self, op_id: str, *, approve: bool = False) -> dict[str, Any]:
        """Run a finished operation's step again, with the flags it had.

        A new operation id is minted rather than reusing the old record, so
        the failed attempt's logs survive for comparison. The rerun is gated
        by policy afresh — approving an operation once does not license
        repeating it.

        **PARAMETERS:**
            `op_id` (str): A finished operation, from `list_operations`.  <br>
            `approve` (bool): Whether the caller approves, when the policy asks.  <br>

        **RETURNS:**
            `dict[str, Any]`: The new run's outcome, plus the id it was rerun from.  <br>

        **RAISES:**
            `FleetError`: If `op_id` is unknown or still running.  <br>
            `ApprovalRequired`: If the policy asks and `approve` is false.  <br>
            `PolicyDenied`: If the policy refuses outright.  <br>
        """
        operation = self.container.operations.get(op_id)
        if operation is None:
            raise FleetError(f"Unknown operation: {op_id}")
        if operation.status is OperationStatus.RUNNING:
            raise FleetError(f"{op_id} is still running; cancel it before rerunning.")

        outcome = self.run_step(operation.step_id, device_id=operation.target or None, params=operation.params, approve=approve)
        return {**outcome, "rerun_of": op_id}

    def start_step(self, step_id: str, *, device_id: str | None = None, params: Mapping[str, Any] | None = None, approve: bool = False) -> dict[str, Any]:
        """Start a step in the background and return its id immediately.

        Policy is applied before dispatch, not inside the worker: a caller
        must learn it needs approval when it asks, not by polling an
        operation that already failed. Poll `get_operation` for progress.

        **PARAMETERS:**
            `step_id` (str): Which step, from `list_steps`.  <br>
            `device_id` (str | None): Target device for a device-scoped step.  <br>
            `params` (Mapping[str, Any] | None): Step parameters.  <br>
            `approve` (bool): Whether the caller approves, when the policy asks.  <br>

        **RETURNS:**
            `dict[str, Any]`: The new operation's id and target.  <br>

        **RAISES:**
            `FleetError`: If the step or device is unknown, or the device is busy.  <br>
            `ApprovalRequired`: If the policy asks and `approve` is false.  <br>
            `PolicyDenied`: If the policy refuses outright.  <br>
        """
        step, op_id = self._authorize(step_id, device_id, approve=approve)

        # Checked here as well as in the runner so a busy device is an error
        # the caller sees, not an operation that fails a moment later.
        busy = self.container.operations.running_for(device_id) if device_id else None
        if busy is not None:
            raise FleetError(f"{device_id} is busy with {busy}; wait for it or cancel it before starting {step_id}")

        flags = dict(params or {})
        self.container.dispatcher.submit(op_id, lambda: self._invoke_tracked(step, device_id, flags, op_id))
        return {"op_id": op_id, "step": step_id, "target": device_id or "fleet", "status": OperationStatus.RUNNING.value}

    def _invoke_tracked(self, step: RegisteredStep, device_id: str | None, flags: dict[str, Any], op_id: str) -> OperationStatus | None:
        """Run a backgrounded step, guaranteeing the operation reaches a terminal status.

        `_invoke` only reaches `run_step` — the thing that finishes an
        operation — after it has resolved a transport, a pack, capabilities
        and a state manager. Anything that raises before that point leaves the
        operation RUNNING forever: no output, no failure, and deaf to cancel,
        because cancellation is only observed inside the step body. An
        unreachable device does exactly that.

        The dispatcher cannot do this itself; it holds no registry.

        **RETURNS:**
            `OperationStatus | None`: The terminal status, or ``None`` when setup failed and this marked the operation failed.  <br>
        """
        try:
            return self._invoke(step, device_id, flags, op_id)
        except Exception as exc:  # noqa: BLE001 - any setup failure must still land the operation
            LOGGER.warning("Operation %s failed before its body ran: %s", op_id, exc)
            operations = self.container.operations
            # `_authorize` mints the id; `run_step` is what registers the
            # operation. Failing before that means there is no record to fail,
            # so it has to be created here — otherwise the panel keeps showing
            # the id `start_step` handed it, with nothing behind it.
            handle = OperationHandle(operations, op_id) if operations.get(op_id) else operations.start(op_id, step.spec.id, device_id or "", flags)
            handle.log(f"Error: {exc}")
            handle.fail(str(exc))
            return None

    def set_gold_device(self, device_id: str) -> dict[str, Any]:
        """Designate `device_id` as the sole device carrying the ``gold`` tag.

        Which device is "gold" — the reference capture source — is picked at
        any time, not fixed in config: a caller (a panel button, an agent)
        may retarget it on the fly. Exclusive, so exactly one device carries
        the tag at once, matching what `kodi-capture-gold`'s `targets:
        {tags: [gold]}` expects.

        **PARAMETERS:**
            `device_id` (str): The device to designate.  <br>

        **RETURNS:**
            `dict[str, Any]`: The updated device.  <br>

        **RAISES:**
            `FleetError`: If `device_id` is not in the inventory.  <br>
        """
        device = self.container.inventory.set_tag(device_id, "gold", exclusive=True)
        with correlate(actor=self.actor):
            self.container.audit.write(
                AuditEvent.build(
                    AuditKind.CONFIG,
                    "inventory.set_gold_device",
                    target=device_id,
                    outcome=Outcome.OK,
                    detail={"surface": "agent"},
                )
            )
        return {"id": device.id, "tags": list(device.tags)}

    def forget_device(self, device_id: str) -> dict[str, Any]:
        """Drop a device from the inventory, so it returns only when a scan finds it again.

        A scan deliberately keeps a device it did not see: absence from one
        sweep is not evidence a device is gone, and a box that is merely off
        would otherwise vanish along with its tags and per-app vars. Removing
        one is therefore an explicit decision, made here.

        Refused while the device has work running. A forgotten device whose
        operation is still going would leave that operation reporting against
        an id the inventory no longer knows.

        **PARAMETERS:**
            `device_id` (str): The device to forget.  <br>

        **RETURNS:**
            `dict[str, Any]`: The id, whether a record was actually removed, and the tags it carried, so a caller can say what was lost.  <br>

        **RAISES:**
            `FleetError`: If the device is busy with a running operation.  <br>
        """
        device = self.container.inventory.get(device_id)
        tags = list(device.tags) if device else []

        busy = self.container.operations.running_for(device_id)
        if busy is not None:
            raise FleetError(f"{device_id} is busy with {busy}; wait for it or cancel it before forgetting the device")

        removed = self.container.inventory.forget(device_id)
        with correlate(actor=self.actor):
            self.container.audit.write(
                AuditEvent.build(
                    AuditKind.CONFIG,
                    "inventory.forget_device",
                    target=device_id,
                    outcome=Outcome.OK if removed else Outcome.SKIPPED,
                    detail={"surface": "agent", "tags": tags},
                )
            )
        return {"id": device_id, "removed": removed, "tags": tags}

    # -- Internal ----------------------------------------------------------

    def _authorize(self, step_id: str, device_id: str | None, *, approve: bool) -> tuple[RegisteredStep, str]:
        """Resolve a step, check it is allowed, and mint its operation id.

        **RETURNS:**
            `tuple[RegisteredStep, str]`: The step and its new operation id.  <br>

        **RAISES:**
            `FleetError`: If the step or device is unknown, or the device is not actionable.  <br>
            `ApprovalRequired`: If the policy asks and `approve` is false.  <br>
            `PolicyDenied`: If the policy refuses outright.  <br>
        """
        step = self.container.registry.step(step_id)
        device = self.container.inventory.get(device_id) if device_id else None
        if device_id and device is None:
            raise FleetError(f"Unknown device: {device_id}")
        if device is not None and not device.is_actionable:
            raise FleetError(f"{device.id} is {device.status.value}; it cannot be acted on until that is resolved.")

        decision = self.container.policy.check(actor=self.actor, step_id=step_id, effect=step.spec.effect, device=device)
        if decision.verdict is Verdict.DENY:
            self._record_denial(step_id, device_id or "fleet", decision.reason)
            raise PolicyDenied(decision.reason)
        if decision.verdict is Verdict.CONFIRM and not approve:
            raise ApprovalRequired(decision.reason, (f"{step_id} on {device_id or 'fleet'}",))

        return step, self.container.operations.new_id(f"{self.actor.replace(':', '-')}-{step_id.replace('.', '-')}")

    def _invoke(self, step: RegisteredStep, device_id: str | None, flags: dict[str, Any], op_id: str) -> OperationStatus:
        """Run a step through the CLI's runners, unwrapping their `click.ClickException` so it never reaches a non-CLI caller.

        **RETURNS:**
            `OperationStatus`: The terminal status.  <br>

        **RAISES:**
            `FleetError`: Whatever the step raised, with the CLI's wrapper removed.  <br>
        """
        import click  # noqa: PLC0415 - only needed to unwrap the CLI's own error type

        from ..cli.main import _run_device_step, _run_fleet_step  # noqa: PLC0415 - avoids a cycle at import time

        try:
            if step.spec.scope == "device":
                return _run_device_step(self.container, step, device_id, flags, op_id)
            return _run_fleet_step(self.container, step, flags, op_id)
        except click.ClickException as exc:
            raise FleetError(exc.format_message()) from exc.__cause__ or exc

    def _plan(self, name: str) -> Plan:
        workflows = self.container.workflows()
        if name not in workflows:
            known = ", ".join(sorted(workflows)) or "none"
            raise FleetError(f"No workflow {name!r} (known: {known})")
        return build_plan(
            workflows[name],
            self.container.registry,
            self.container.inventory.list(),
            policy=self.container.policy,
            actor=self.actor,
        )

    def _execute(self, plan: Plan) -> dict[str, Any]:
        from ..cli.main import _task_runner  # noqa: PLC0415 - avoids a cycle at import time

        engine = WorkflowEngine(_task_runner(self.container), self.container.audit, actor=self.actor)
        report = engine.run(plan)
        return {
            "workflow": report.workflow,
            "run_id": report.run_id,
            "summary": report.summary(),
            "succeeded": report.succeeded,
            "stopped_early": report.stopped_early,
            "tasks": [
                {"op_id": outcome.op_id, "step": outcome.task.step_id, "target": outcome.task.target_id, "status": outcome.status.value}
                for outcome in report.outcomes
            ],
            "failed": [outcome.task.target_id for outcome in report.failed],
        }

    def _record_denial(self, step_id: str, target: str, reason: str) -> None:
        with correlate(actor=self.actor, step_id=step_id):
            self.container.audit.write(
                AuditEvent.build(
                    AuditKind.DECISION,
                    f"policy.deny {step_id}",
                    target=target,
                    outcome=Outcome.DENIED,
                    detail={"reason": reason, "surface": "agent"},
                )
            )


def _describe(plan: Plan) -> dict[str, Any]:
    return {
        "workflow": plan.workflow,
        "digest": plan.digest(),
        "device_count": plan.device_count,
        "empty": plan.is_empty,
        "tasks": [_task(task) for step in plan.steps for task in step.tasks],
        "blocked": [_task(task) for task in plan.blocked],
        "needs_approval": [_task(task) for task in plan.needs_approval],
        "confirm_with": plan.digest(),
    }


def _task(task: PlannedTask) -> dict[str, Any]:
    return {
        "step": task.step_id,
        "use": task.use,
        "target": task.target_id,
        "effect": task.effect.value,
        "runnable": task.runnable,
        "blocked": task.blocked or None,
        "needs_approval": task.needs_approval or None,
    }


__all__ = ["ApprovalRequired", "PolicyDenied", "Toolkit", "OperationStatus"]
