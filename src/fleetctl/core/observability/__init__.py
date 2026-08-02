"""Three streams, deliberately separate.

- Diagnostic logging — verbose, per-subsystem, short retention.
- The operation timeline — human-readable progress for the UI.
- The audit trail — append-only, structured, records effects rather than
  narrative.

They have different readers, different retention, and different security
postures. Conflating them is what makes a fleet tool undiagnosable after the
fact.
"""

from __future__ import annotations
