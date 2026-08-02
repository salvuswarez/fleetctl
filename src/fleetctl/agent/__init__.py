"""The agent-facing surface.

Deliberately a plain Python API with no protocol dependency. The MCP server
is a thin binding over this, which keeps the interesting parts — policy
gating, approval, plan confirmation — testable without speaking a wire
protocol, and leaves room for a second binding later without moving any of
the logic.
"""

from __future__ import annotations
