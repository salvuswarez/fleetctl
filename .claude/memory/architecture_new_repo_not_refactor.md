---
name: fleetctl is a new repo, not a refactor of firestick_manager
description: S0-S7 are done (S7 cutover landed 2026-08-06). firestick_manager has been retired; only S8 (later) remains.
type: project
---

`fleetctl` was started fresh (2026-08-01) rather than refactoring `firestick_manager` in place. **S0–S6
were done as of 2026-08-02** — transport, packs (firetv/shield), the kodi app, config-as-code,
workflows, policy, audit, and MCP all exist, are tested (500+ tests, mypy strict, ~90.6% coverage), and
had run against real hardware (scan, capture, build, deploy all executed on real Fire TV sticks). **S7
(HA cutover) landed 2026-08-06** — `ha-cyberpunk` repins to `fleetctl`, and the predecessor repo has
been retired. See `docs/roadmap.md` for the stage table and `docs/ha-parity.md` for the audited command
mapping S7 satisfied.

Stage ordering has two hard constraints: **S1 before everything** (both `ArtifactStore` adapters land there, and the local one is what makes S2 testable at all), and **S4 before S6** (policy and audit precede the MCP adapter — shipping agent-facing tools over a fleet with no policy layer and no audit record is the one decision that is hard to walk back). **S2 is the honesty gate**: feature parity against real hardware before any of the interesting work. **S5 validates the design** — if adding the Shield requires touching `core/` or `apps/kodi/`, the seams are wrong.

**Why:** An in-place refactor would have meant a coordinated release with `ha-cyberpunk` on every intermediate step, since its `manifest.json` pins `firestick_manager` by git tag and imports `fire_tools` directly. A parallel build makes the cutover a single planned event instead of a standing risk.

**How to apply:** Check the `build-stages` skill before starting work, and refuse to build ahead of the current stage — no empty subpackages "ready for later", no abstraction whose second adapter is a future stage. See [[architecture_rings_and_decisions]] and [[reference_predecessor_firestick_manager]].
