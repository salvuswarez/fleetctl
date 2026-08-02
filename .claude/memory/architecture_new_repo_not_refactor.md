---
name: fleetctl is a new repo, not a refactor of firestick_manager
description: firestick_manager keeps running untouched until the S7 cutover; fleetctl is built in parallel in stages S0-S8.
type: project
---

`fleetctl` was started fresh (2026-08-01) rather than refactoring `firestick_manager` in place. The predecessor keeps running and keeps serving the Home Assistant integration until stage **S7**, when HA repins to `fleetctl` and the old repo is archived.

Stage ordering has two hard constraints: **S1 before everything** (both `ArtifactStore` adapters land there, and the local one is what makes S2 testable at all), and **S4 before S6** (policy and audit precede the MCP adapter — shipping agent-facing tools over a fleet with no policy layer and no audit record is the one decision that is hard to walk back). **S2 is the honesty gate**: feature parity against real hardware before any of the interesting work. **S5 validates the design** — if adding the Shield requires touching `core/` or `apps/kodi/`, the seams are wrong.

**Why:** An in-place refactor would have meant a coordinated release with `ha-cyberpunk` on every intermediate step, since its `manifest.json` pins `firestick_manager` by git tag and imports `fire_tools` directly. A parallel build makes the cutover a single planned event instead of a standing risk.

**How to apply:** Check the `build-stages` skill before starting work, and refuse to build ahead of the current stage — no empty subpackages "ready for later", no abstraction whose second adapter is a future stage. See [[architecture_rings_and_decisions]] and [[reference_predecessor_firestick_manager]].
