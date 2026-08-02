"""The `fleetctl` command group."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import click
import yaml

from .._version import get_version
from ..core.config.layering import for_device
from ..core.discovery.scan import Scanner, ScanOutcome
from ..core.errors import FleetError
from ..core.observability.audit import AuditEvent, AuditKind, Outcome, verify_chain
from ..core.observability.correlation import CorrelationFilter, correlate
from ..core.operations.registry import OperationStatus
from ..core.policy import Verdict
from ..core.registry import RegisteredStep
from ..core.transport.base import Transport
from ..core.workflow.engine import WorkflowEngine
from ..core.workflow.plan import build_plan
from ..core.workflow.runner import check_capabilities, run_step
from ..core.workflow.step import DeviceStepContext, DiscoveryStepContext, FleetStepContext, StepResult, TransformStepContext
from .bootstrap import Container, build_container

LOGGER = logging.getLogger(__name__)

_LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(op_id)s] %(name)s: %(message)s"


def configure_logging(verbose: int) -> None:
    """Send diagnostic logging to stderr, annotated with correlation ids.

    **PARAMETERS:**
        `verbose` (int): Count of ``-v`` flags. ``0`` shows warnings and worse, ``1`` adds info, ``2`` or more adds debug.  <br>
    """
    level = {0: logging.WARNING, 1: logging.INFO}.get(verbose, logging.DEBUG)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    # On the handler, not a logger, so records from libraries are annotated too.
    handler.addFilter(CorrelationFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(get_version(), "-V", "--version", prog_name="fleetctl")
@click.option("-v", "--verbose", count=True, help="Increase log verbosity; repeat for debug.")
@click.option("--config-dir", type=click.Path(path_type=Path), default=None, help="Directory holding fleet.yml and inventory/. Defaults to ./config.")
@click.option("--home", type=click.Path(path_type=Path), default=None, help="Runtime state directory. Defaults to ~/.fleetctl.")
@click.pass_context
def main(ctx: click.Context, verbose: int, config_dir: Path | None, home: Path | None) -> None:
    """Manage a fleet of home devices."""
    configure_logging(verbose)
    ctx.obj = {"config_dir": config_dir, "home": home}


def _container(ctx: click.Context) -> Container:
    options = ctx.obj or {}
    return build_container(config_dir=options.get("config_dir"), home=options.get("home"))


@main.command(name="packs")
@click.pass_context
def list_packs(ctx: click.Context) -> None:
    """List installed device packs and app packs."""
    container = _container(ctx)
    packs = container.registry.device_packs()
    if not packs:
        click.echo("No device packs installed.")
    for pack in packs:
        verbs = ", ".join(sorted(capability.value for capability in pack.capabilities))
        click.echo(f"{pack.id:<12} platform={pack.platform:<10} {verbs}")


@main.command(name="steps")
@click.pass_context
def list_steps(ctx: click.Context) -> None:
    """List every registered step."""
    container = _container(ctx)
    for step in container.registry.steps():
        click.echo(f"{step.spec.id:<20} [{step.spec.effect.value:<11}] {step.spec.summary}")


@main.group()
def devices() -> None:
    """Inspect the known fleet."""


@devices.command(name="list")
@click.pass_context
def devices_list(ctx: click.Context) -> None:
    """List known devices."""
    container = _container(ctx)
    known = container.inventory.list()
    if not known:
        click.echo("No devices in inventory.")
        return
    for device in known:
        tags = ",".join(device.tags) or "-"
        marker = "" if device.is_actionable else f"  [{device.status.value}]"
        click.echo(f"{device.id:<16} {device.type or '?':<10} {device.address or '?':<16} tags={tags}{marker}")


@main.command(name="config")
@click.argument("device_id")
@click.pass_context
def show_config(ctx: click.Context, device_id: str) -> None:
    """Explain the resolved config for a device, layer by layer."""
    container = _container(ctx)
    device = container.inventory.get(device_id)
    if device is None:
        raise click.ClickException(f"Unknown device: {device_id}")
    resolved = for_device(fleet=dict(container.config), device=device.vars)
    for line in resolved.explain():
        click.echo(line)


@main.command(name="run")
@click.argument("step_id")
@click.option("--device", "device_id", default=None, help="Target device id. Required for device-scoped steps.")
@click.option("--set", "overrides", multiple=True, metavar="KEY=VALUE", help="Config override for this run; repeatable.")
@click.option("--approve", is_flag=True, help="Approve a step the policy flagged as needing it.")
@click.pass_context
def run(ctx: click.Context, step_id: str, device_id: str | None, overrides: tuple[str, ...], approve: bool) -> None:
    """Run a registered step. Use `fleetctl steps` to see what is available."""
    container = _container(ctx)
    try:
        step = container.registry.step(step_id)
    except FleetError as exc:
        raise click.ClickException(str(exc)) from exc

    flags = _parse_overrides(overrides)
    op_id = container.operations.new_id(step_id.replace(".", "-"))

    device = container.inventory.get(device_id) if device_id else None
    decision = container.policy.check(actor=container.actor, step_id=step_id, effect=step.spec.effect, device=device)
    if decision.denied:
        _record_denial(container, step_id, device_id or "fleet", decision.reason)
        raise click.ClickException(decision.reason)
    # `workflow run` has always honoured this; a single step ignoring it made
    # `confirm:` decorative on the shortest path to a destructive change.
    if decision.verdict is Verdict.CONFIRM and not approve:
        raise click.ClickException(f"{decision.reason}. Re-run with --approve once you have reviewed what it will change.")

    if step.spec.scope == "device":
        status = _run_device_step(container, step, device_id, flags, op_id)
    else:
        status = _run_fleet_step(container, step, flags, op_id)

    operation = container.operations.get(op_id)
    for entry in operation.logs if operation else []:
        click.echo(f"[*] {entry['message']}")

    if status is not OperationStatus.COMPLETED:
        raise click.ClickException((operation.result if operation else None) or f"{step_id} did not complete")
    click.echo(f"[+] {operation.result if operation else step_id}")


def _run_device_step(container: Container, step: RegisteredStep, device_id: str | None, flags: dict[str, Any], op_id: str) -> OperationStatus:
    if not device_id:
        raise click.UsageError(f"{step.spec.id} targets a device; pass --device")
    device = container.inventory.get(device_id)
    if device is None:
        raise click.ClickException(f"Unknown device: {device_id}")

    resolved = for_device(fleet=dict(container.config), device=device.vars, flags=flags)
    transport: Transport | None = None
    try:
        transport = container.transport_for(device)
        check_capabilities(step.spec, transport)
        state = container.state_for(device, transport)
        app_manager = container.apps_for(device, transport)

        def body(handle: Any, workspace: Path) -> StepResult:
            return step.run(
                DeviceStepContext(
                    device=device,
                    transport=transport,
                    state=state,
                    apps=app_manager,
                    artifacts=container.artifacts,
                    inventory=container.inventory,
                    config=resolved.values,
                    handle=handle,
                    workspace=workspace,
                )
            )

        return run_step(
            container.operations,
            step.spec,
            body,
            op_id=op_id,
            target=device.id,
            actor=container.actor,
            run_id=op_id,
            params=flags,
            staging_root=container.staging_root,
            failures_root=container.failures_root,
        )
    except FleetError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        if transport is not None:
            transport.close()


def _run_fleet_step(container: Container, step: RegisteredStep, flags: dict[str, Any], op_id: str) -> OperationStatus:
    resolved = for_device(fleet=dict(container.config), flags=flags)
    transforms = _transforms_for(container, step.provider)

    def body(handle: Any, workspace: Path) -> StepResult:
        if step.spec.scope == "transform":
            return step.run(
                TransformStepContext(
                    transforms=transforms,
                    artifacts=container.artifacts,
                    config=resolved.values,
                    handle=handle,
                    workspace=workspace,
                )
            )
        if step.spec.scope == "discovery":
            return step.run(DiscoveryStepContext(scanner=_scanner(container), config=resolved.values, handle=handle, workspace=workspace))
        return step.run(
            FleetStepContext(
                artifacts=container.artifacts,
                inventory=container.inventory,
                config=resolved.values,
                handle=handle,
                workspace=workspace,
            )
        )

    return run_step(
        container.operations,
        step.spec,
        body,
        op_id=op_id,
        actor=container.actor,
        run_id=op_id,
        params=flags,
        staging_root=container.staging_root,
        failures_root=container.failures_root,
    )


def _transforms_for(container: Container, provider: str) -> tuple[Any, ...]:
    """RETURNS: tuple: The provider app's transform chain, or empty if it has none."""
    try:
        app = container.registry.app_pack(provider)
    except FleetError:
        return ()
    return tuple(getattr(app, "transforms", ()))


def _parse_overrides(overrides: tuple[str, ...]) -> dict[str, Any]:
    """Turn `--set` entries into a config layer.

    Dotted keys nest, so `--set kodi.display.resolution_index=18` lands where
    a device's `vars` would have put it and merges with the rest rather than
    replacing the branch. Values are read as YAML scalars, so numbers and
    booleans arrive typed.

    **PARAMETERS:**
        `overrides` (tuple[str, ...]): Raw `KEY=VALUE` entries.  <br>

    **RETURNS:**
        `dict[str, Any]`: A nested mapping, ready to merge as the highest layer.  <br>

    **RAISES:**
        `click.UsageError`: If an entry is not `KEY=VALUE`.  <br>
    """
    parsed: dict[str, Any] = {}
    for entry in overrides:
        key, separator, raw = entry.partition("=")
        if not separator:
            raise click.UsageError(f"--set expects KEY=VALUE, got {entry!r}")
        try:
            value = yaml.safe_load(raw.strip())
        except yaml.YAMLError:
            value = raw.strip()

        branch = parsed
        *parents, leaf = [part.strip() for part in key.strip().split(".")]
        for part in parents:
            existing = branch.get(part)
            branch[part] = existing if isinstance(existing, dict) else {}
            branch = branch[part]
        branch[leaf] = raw.strip() if value is None else value
    return parsed


@main.group()
def artifacts() -> None:
    """Inspect stored artifacts."""


@artifacts.command(name="list")
@click.argument("kind")
@click.pass_context
def artifacts_list(ctx: click.Context, kind: str) -> None:
    """List artifacts of a kind, newest first (e.g. captures, builds)."""
    container = _container(ctx)
    found = container.artifacts.list(kind)
    if not found:
        click.echo(f"No artifacts of kind {kind!r}.")
        return
    for info in found:
        click.echo(f"{info.ref.wire:<44} {info.size // 1024:>8}KB  {info.created_at}")


@main.group()
def audit() -> None:
    """Inspect the audit trail."""


@audit.command(name="verify")
@click.pass_context
def audit_verify(ctx: click.Context) -> None:
    """Verify the audit trail's hash chain is unbroken."""
    container = _container(ctx)
    events = container.audit.records()
    if not events:
        click.echo("No audit records found.")
        return
    intact, first_bad = verify_chain(events)
    if intact:
        click.echo(f"[+] {len(events)} record(s) verified; chain intact.")
        return
    raise click.ClickException(f"Audit chain broken at record {first_bad}")


@audit.command(name="tail")
@click.option("-n", "count", default=20, show_default=True, help="How many records to show.")
@click.pass_context
def audit_tail(ctx: click.Context, count: int) -> None:
    """Show the most recent audit records."""
    container = _container(ctx)
    for event in container.audit.records()[-count:]:
        target = event.target or "-"
        click.echo(f"{event.ts}  {event.actor:<12} {target:<16} {event.outcome.value:<8} {event.action}")


if __name__ == "__main__":
    main()


@main.group()
def workflow() -> None:
    """Plan and run workflows."""


@workflow.command(name="list")
@click.pass_context
def workflow_list(ctx: click.Context) -> None:
    """List available workflows."""
    container = _container(ctx)
    available = container.workflows()
    if not available:
        click.echo("No workflows available.")
        return
    for name in sorted(available):
        steps = len(available[name].steps)
        click.echo(f"{name:<20} {steps} step(s)  {available[name].description.strip().splitlines()[0] if available[name].description else ''}")


def _plan_for(container: Container, name: str) -> Any:
    available = container.workflows()
    if name not in available:
        known = ", ".join(sorted(available)) or "none"
        raise click.ClickException(f"No workflow {name!r} (known: {known})")
    try:
        return build_plan(available[name], container.registry, container.inventory.list(), policy=container.policy, actor=container.actor)
    except FleetError as exc:
        raise click.ClickException(str(exc)) from exc


@workflow.command(name="plan")
@click.argument("name")
@click.pass_context
def workflow_plan(ctx: click.Context, name: str) -> None:
    """Show everything a workflow would do, without doing any of it."""
    container = _container(ctx)
    plan = _plan_for(container, name)
    for line in plan.describe():
        click.echo(line)
    click.echo(f"\ndigest: {plan.digest()}")
    if plan.is_empty:
        click.echo("Nothing to do: no target matched any device.")
    blocked = plan.blocked
    if blocked:
        click.echo(f"{len(blocked)} task(s) blocked and will be skipped.")
    pending = plan.needs_approval
    if pending:
        click.echo(f"{len(pending)} task(s) need approval; re-run with --approve.")


@workflow.command(name="run")
@click.argument("name")
@click.option("--dry-run", is_flag=True, help="Show the plan and stop.")
@click.option("--confirm", "expected_digest", default=None, help="Refuse to run unless the plan still matches this digest.")
@click.option("--approve", is_flag=True, help="Approve tasks the policy flagged as needing it.")
@click.pass_context
def workflow_run(ctx: click.Context, name: str, dry_run: bool, expected_digest: str | None, approve: bool) -> None:
    """Run a workflow."""
    container = _container(ctx)
    plan = _plan_for(container, name)

    if dry_run:
        for line in plan.describe():
            click.echo(line)
        click.echo(f"\ndigest: {plan.digest()}")
        click.echo("Dry run: nothing was executed.")
        return

    if expected_digest and expected_digest != plan.digest():
        raise click.ClickException(f"The fleet changed since that plan was made (now {plan.digest()}). Re-plan and try again.")

    if plan.is_empty:
        click.echo("Nothing to do: no target matched any device.")
        return

    radius = container.policy.check_blast_radius(actor=container.actor, device_count=plan.device_count)
    if radius.denied:
        raise click.ClickException(radius.reason)

    pending = plan.needs_approval
    if pending and not approve:
        for task in pending:
            click.echo(f"[?] {task.step_id} {task.target_id}: {task.needs_approval}")
        raise click.ClickException("Approval required; re-run with --approve once you have reviewed the plan.")

    engine = WorkflowEngine(_task_runner(container), container.audit, actor=container.actor)
    report = engine.run(plan)

    for outcome in report.outcomes:
        operation = container.operations.get(outcome.op_id)
        marker = "+" if outcome.status is OperationStatus.COMPLETED else "!"
        click.echo(f"[{marker}] {outcome.task.step_id} {outcome.task.target_id}: {(operation.result if operation else outcome.status.value)}")

    click.echo(report.summary())
    if not report.succeeded:
        raise click.ClickException("Workflow did not complete cleanly")


def _record_denial(container: Container, step_id: str, target: str, reason: str) -> None:
    """Audit a refusal."""
    # Bound here because a denial happens before any step envelope runs, and a
    # record that cannot say who was refused is half a record.
    with correlate(actor=container.actor, step_id=step_id):
        container.audit.write(AuditEvent.build(AuditKind.DECISION, f"policy.deny {step_id}", target=target, outcome=Outcome.DENIED, detail={"reason": reason}))


def _task_runner(container: Container) -> Any:
    """Build the callback the engine uses to execute one planned task."""

    def _run(task: Any, op_id: str) -> OperationStatus:
        step = container.registry.step(task.use)
        flags = dict(task.params)
        if task.device is None:
            return _run_fleet_step(container, step, flags, op_id)
        return _run_device_step(container, step, task.device.id, flags, op_id)

    return _run


def _scanner(container: Container) -> Scanner:
    """RETURNS: Scanner: A scanner wired to this container's packs and inventory."""
    return Scanner(packs=container.registry.device_packs(), connect=container.connector(), inventory=container.inventory)


@main.command(name="scan")
@click.argument("subnet")
@click.option("--dry-run", is_flag=True, help="Report what was found without writing the inventory.")
@click.pass_context
def scan(ctx: click.Context, subnet: str, dry_run: bool) -> None:
    """Discover devices on a subnet and merge them into the inventory."""
    container = _container(ctx)
    try:
        outcome = _scanner(container).run(subnet, dry_run=dry_run)
    except FleetError as exc:
        raise click.ClickException(str(exc)) from exc
    _report_scan(container, outcome)


def _report_scan(container: Container, outcome: ScanOutcome) -> None:
    """Print a scan, in the detail a terminal wants and the facts do not carry."""
    click.echo(f"{outcome.responded} host(s) responded on {outcome.subnet}")
    for claim in outcome.identified:
        if claim.device is not None:
            click.echo(f"  {claim.device.id:<20} {claim.pack_id:<10} {claim.host.address:<16} {claim.device.model}")

    # Unrecognized hosts are summarised, not listed. On a real /24 they are
    # the overwhelming majority, and 250 lines of noise buries the few that
    # matter. `-v` lists them for when a device you expected is missing.
    if outcome.unrecognized:
        click.echo(f"  ({len(outcome.unrecognized)} host(s) not recognized by any installed pack; -v lists them)")
        for address in outcome.unrecognized:
            LOGGER.info("Unrecognized host: %s", address)
    if outcome.unauthorized:
        click.echo("")
        click.echo(f"  {len(outcome.unauthorized)} host(s) are reachable but refused this key: {', '.join(outcome.unauthorized)}")
        click.echo("  Approve the debugging prompt on those devices, or copy an already-trusted key into")
        click.echo(f"  {container.home / 'keys'}, then scan again.")

    if not outcome.recordable:
        click.echo("No devices found. Devices need network debugging enabled to be discovered.")
        return
    if not outcome.written:
        click.echo(f"\nDry run: {len(outcome.recordable)} device(s) found, inventory not written.")
        return

    click.echo(f"\nAdded {outcome.added}, updated {outcome.updated}, {outcome.total} device(s) total.")
    click.echo(f"Inventory: {container.inventory_path}")
    click.echo("Edit that file directly to set tags, names, or per-app vars — a scan never overwrites them.")


@main.command(name="mcp")
@click.option("--actor", default="mcp:agent", help="Identity recorded on every audit record and matched against policy.")
@click.pass_context
def mcp_serve(ctx: click.Context, actor: str) -> None:
    """Serve the agent toolkit over MCP on stdio."""
    options = ctx.obj or {}
    try:
        from ..mcp.server import serve
    except ImportError as exc:  # pragma: no cover - depends on an optional extra
        raise click.ClickException("MCP support is optional: pip install 'fleetctl[mcp]'") from exc
    try:
        serve(config_dir=options.get("config_dir"), home=options.get("home"), actor=actor)
    except FleetError as exc:
        raise click.ClickException(str(exc)) from exc
