"""An MCP server exposing the agent toolkit.

Deliberately thin. Every decision that matters — what is allowed, what needs
approval, whether a plan is still current — lives in `agent.toolkit` and is
tested without a protocol. This module maps that surface onto MCP and
translates exceptions into messages an agent can act on.

Two shaping choices:

**Reads are resources; changes are tools.** Listing devices or tailing the
audit log is a resource read, which keeps the mutating tool surface small
enough to review. Four tools can change something, and each is gated.

**Errors are answers, not stack traces.** An approval requirement comes back
as text naming exactly what needs approving and how to proceed, because an
agent that receives a traceback will retry rather than ask.
"""

from __future__ import annotations

import importlib
import json
import logging
from pathlib import Path
from typing import Any

from ..agent.toolkit import ApprovalRequired, PolicyDenied, Toolkit
from ..cli.bootstrap import build_container
from ..core.errors import FleetError

LOGGER = logging.getLogger(__name__)

SERVER_NAME = "fleetctl"


def _render(payload: Any) -> str:
    return json.dumps(payload, indent=2, default=str)


def _new_server() -> Any:
    """Construct a server across SDK layouts.

    The Python MCP SDK has moved this class between modules; both spellings
    expose the same `tool`/`resource` decorators and `run()`, so trying each
    is cheaper than pinning users to one SDK release.

    **RETURNS:**
        `Any`: A server instance.  <br>

    **RAISES:**
        `FleetError`: If the optional dependency is absent or has moved again.  <br>
    """
    candidates = (("mcp.server.mcpserver", "MCPServer"), ("mcp.server.fastmcp", "FastMCP"))
    for module_name, class_name in candidates:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        factory = getattr(module, class_name, None)
        if factory is not None:
            return factory(SERVER_NAME)
    raise FleetError(
        "The MCP server needs the optional dependency: pip install 'fleetctl[mcp]'. " "If it is installed, the SDK may have moved its server class again."
    )


def build_server(toolkit: Toolkit) -> Any:
    """Wire the toolkit onto an MCP server.

    **PARAMETERS:**
        `toolkit` (Toolkit): The policy-aware operations to expose.  <br>

    **RETURNS:**
        `FastMCP`: A server ready to run.  <br>

    **RAISES:**
        `FleetError`: If the optional `mcp` dependency is not installed.  <br>
    """
    server = _new_server()

    @server.resource("fleetctl://devices")
    def devices() -> str:
        """Every known device, including any flagged as unusable."""
        return _render(toolkit.list_devices())

    @server.resource("fleetctl://steps")
    def steps() -> str:
        """Registered steps and the effect class that decides how each is gated."""
        return _render(toolkit.list_steps())

    @server.resource("fleetctl://workflows")
    def workflows() -> str:
        """Available workflows and the steps they run."""
        return _render(toolkit.list_workflows())

    @server.resource("fleetctl://operations")
    def operations() -> str:
        """Operations tracked in this process."""
        return _render(toolkit.list_operations())

    @server.resource("fleetctl://audit")
    def audit() -> str:
        """The most recent audit records, already redacted."""
        return _render(toolkit.audit_tail(50))

    @server.tool()
    def plan_workflow(name: str) -> str:
        """Show everything a workflow would do, without doing any of it.

        Always call this before run_workflow: the digest it returns is what
        run_workflow requires as confirmation.
        """
        return _guard(lambda: _render(toolkit.plan_workflow(name)))

    @server.tool()
    def run_workflow(name: str, confirm: str, approve: bool = False) -> str:
        """Run a workflow.

        `confirm` must be the digest from a recent plan_workflow call. If the
        fleet changed since then the run is refused and you should re-plan.
        Set `approve` only after showing the user what the plan will change.
        """
        return _guard(lambda: _render(toolkit.run_workflow(name, confirm=confirm, approve=approve)))

    @server.tool()
    def run_step(step_id: str, device_id: str | None = None, params: dict[str, Any] | None = None, approve: bool = False) -> str:
        """Run a single step, optionally against one device.

        Set `approve` only after showing the user what the step will change.
        """
        return _guard(lambda: _render(toolkit.run_step(step_id, device_id=device_id, params=params, approve=approve)))

    @server.tool()
    def operation_status(op_id: str) -> str:
        """Report one operation's current status and log."""

        def _lookup() -> str:
            snapshots = {snapshot["id"]: snapshot for snapshot in toolkit.list_operations()}
            if op_id not in snapshots:
                return _render({"error": f"No operation {op_id!r} in this process."})
            return _render(snapshots[op_id])

        return _guard(_lookup)

    return server


def _guard(call: Any) -> str:
    """Turn an exception into something an agent can act on.

    A traceback invites a retry; a sentence naming what to do invites the
    right next call.
    """
    try:
        return str(call())
    except ApprovalRequired as exc:
        return _render(
            {
                "status": "approval_required",
                "message": str(exc),
                "tasks": list(exc.tasks),
                "next": "Show the user exactly what would change, then call again with approve=true if they agree.",
            }
        )
    except PolicyDenied as exc:
        return _render({"status": "denied", "message": str(exc), "next": "This cannot be approved. The fleet's policy file must change."})
    except FleetError as exc:
        return _render({"status": "error", "message": str(exc)})


def serve(*, config_dir: Path | None = None, home: Path | None = None, actor: str = "mcp:agent") -> None:
    """Run the MCP server over stdio until the client disconnects.

    stdio rather than a socket: one local agent, no listening port, and no
    authentication surface of its own to get wrong.

    **PARAMETERS:**
        `config_dir` (Path | None): Directory holding `fleet.yml` and `inventory/`.  <br>
        `home` (Path | None): Runtime state directory.  <br>
        `actor` (str): Identity recorded on every audit record and matched against policy.  <br>
    """
    container = build_container(config_dir=config_dir, home=home, actor=actor)
    build_server(Toolkit(container=container, actor=actor)).run()
