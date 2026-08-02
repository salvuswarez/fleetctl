---
name: three rings and the twelve locked decisions
description: fleetctl is core/packs/apps with inward-only dependencies; twelve architecture questions were resolved up front and recorded in docs/architecture.md §15.
type: project
---

`fleetctl` is three rings — `core/` (device-agnostic kernel), `packs/` (device types), `apps/` (software on devices) — with dependencies pointing **inward only**. An app pack never imports a device pack; it declares required capabilities and the engine resolves the provider. That indirection is the whole reason one Kodi build can target both a Fire Stick and a Shield.

Twelve open questions were closed before any code was written (2026-08-01), recorded as D1–D12 in `docs/architecture.md` §15. The ones that shape day-to-day work: YAML for all user-facing config; secrets held as `!ref` and resolved per consumer (HA config entry / env / keyring); audit to the SMB share by default, 90-day retention, hash-chained; logs split per subsystem and routed by effect class; MCP over stdio with any step allowed but gated by approval; Home Assistant demoted to just another actor under the policy layer.

**Why:** Deciding these up front is what lets the build proceed in stages without re-litigating architecture at every step. The full rationale — including the friction in the predecessor that motivated each — is in the architecture doc, which is tracked and public.

**How to apply:** Read `docs/architecture.md` §15 before proposing an architectural change. If a proposal contradicts a D-number, say so explicitly and argue against the recorded rationale rather than restating the question. See [[architecture_new_repo_not_refactor]] for the build sequencing.
