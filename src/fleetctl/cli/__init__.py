"""Command-line port adapter.

One of several adapters over the same core — alongside the Home Assistant
integration and, later, an MCP server. Commands are derived from the step
registry rather than hand-written, so registering a step yields a command.
"""

from __future__ import annotations
