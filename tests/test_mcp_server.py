"""Tests for the MCP binding.

The binding itself should be boring — the decisions live in the toolkit. What
is worth checking here is the shape of the surface (which operations can
change something) and that a refusal reaches the agent as an instruction
rather than a traceback.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from fleetctl.agent.toolkit import ApprovalRequired, PolicyDenied, Toolkit
from fleetctl.cli.bootstrap import build_container
from fleetctl.core.errors import FleetError
from fleetctl.core.registry import Registry
from fleetctl.mcp.server import SERVER_NAME, _guard, build_server

MUTATING_TOOLS = {"plan_workflow", "run_workflow", "run_step", "operation_status"}
READ_RESOURCES = {
    "fleetctl://devices",
    "fleetctl://steps",
    "fleetctl://workflows",
    "fleetctl://operations",
    "fleetctl://audit",
}


@pytest.fixture
def toolkit(tmp_path: Path) -> Toolkit:
    (tmp_path / "config" / "inventory").mkdir(parents=True)
    (tmp_path / "config" / "fleet.yml").write_text("{}\n", encoding="utf-8")
    container = build_container(config_dir=tmp_path / "config", home=tmp_path / "home", actor="mcp:test", registry=Registry())
    return Toolkit(container=container, actor="mcp:test")


def test_the_server_registers_exactly_the_intended_tools(toolkit: Toolkit) -> None:
    """The mutating surface should stay small enough to review at a glance."""
    # Act
    server = build_server(toolkit)
    names = {tool.name for tool in asyncio.run(server.list_tools())}

    # Assert
    assert names == MUTATING_TOOLS


def test_reads_are_resources_not_tools(toolkit: Toolkit) -> None:
    """Keeping them off the tool surface is what keeps that surface small."""
    # Act
    server = build_server(toolkit)
    uris = {str(resource.uri) for resource in asyncio.run(server.list_resources())}

    # Assert
    assert uris == READ_RESOURCES


def test_the_server_is_named_for_the_project(toolkit: Toolkit) -> None:
    assert build_server(toolkit).name == SERVER_NAME


def test_every_tool_documents_itself_for_the_caller(toolkit: Toolkit) -> None:
    """An agent chooses a tool from its description; a blank one is a trap."""
    # Act
    tools = asyncio.run(build_server(toolkit).list_tools())

    # Assert
    assert all(tool.description and len(tool.description) > 30 for tool in tools)


def test_an_approval_requirement_reaches_the_agent_as_an_instruction() -> None:
    """A traceback invites a retry; a sentence naming the next call does not."""

    # Arrange
    def _raise() -> str:
        raise ApprovalRequired("2 task(s) need approval", ("touch on stub-1", "touch on stub-2"))

    # Act
    payload = json.loads(_guard(_raise))

    # Assert
    assert payload["status"] == "approval_required"
    assert payload["tasks"] == ["touch on stub-1", "touch on stub-2"]
    assert "approve=true" in payload["next"]


def test_a_denial_tells_the_agent_not_to_retry() -> None:
    """Approving cannot answer a denial, and the agent needs to know that
    rather than looping."""

    # Arrange
    def _raise() -> str:
        raise PolicyDenied("gold-1 is protected against kodi.deploy")

    # Act
    payload = json.loads(_guard(_raise))

    # Assert
    assert payload["status"] == "denied"
    assert "cannot be approved" in payload["next"]


def test_an_ordinary_failure_is_reported_without_a_traceback() -> None:
    # Arrange
    def _raise() -> str:
        raise FleetError("No workflow 'nope'")

    # Act
    payload = json.loads(_guard(_raise))

    # Assert
    assert payload["status"] == "error"
    assert payload["message"] == "No workflow 'nope'"


def test_a_successful_call_passes_through_unchanged() -> None:
    # Act / Assert
    assert _guard(lambda: '{"ok": true}') == '{"ok": true}'


def test_an_unexpected_exception_is_not_swallowed() -> None:
    """Only fleet errors are translated. A bug should still look like a bug."""

    # Arrange
    def _raise() -> str:
        raise ZeroDivisionError("this is a defect, not a policy outcome")

    # Act / Assert
    with pytest.raises(ZeroDivisionError):
        _guard(_raise)


def test_the_binding_needs_no_hardware_or_network(toolkit: Toolkit) -> None:
    """Building the server must not reach for a device, or an agent could not
    connect to a fleet that is asleep."""
    # Act
    server = build_server(toolkit)

    # Assert
    assert asyncio.run(server.list_tools())
