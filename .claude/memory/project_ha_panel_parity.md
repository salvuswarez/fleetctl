---
name: HA Panel Parity Is the Cutover Gate
description: The ha-cyberpunk panel drives 21 websocket commands; fleetctl must cover all of them before S7. The audited mapping lives in docs/ha-parity.md.
type: project
---

The `firetools` integration wraps `fire_tools.FleetService` one-to-one over 21
websocket commands. Auditing them against fleetctl (2026-08-02) found three
gaps that were not obvious from the step list: `scan` existed only as a CLI
command, `StepResult.facts` was dropped by the runner so no caller saw
structured results, and there was no artifact listing for the backups panel.
All three are closed; `docs/ha-parity.md` is the mapping.

**Why:** "port the workflows" reads as a step-list exercise, and the step list
looked complete while three panel buttons would have done nothing.

**How to apply:** before claiming parity for any consumer, enumerate the
consumer's calls and map each one. See [[architecture_rings_and_decisions]]
for where a new capability belongs, and [[reference_predecessor_firestick_manager]]
for the source being ported.
