---
name: build-stages
description: The S0–S8 build stages, what each contains, its exit criterion, and what is done so far. Use when starting work, deciding whether something is in scope yet, or checking whether a prerequisite stage has landed.
---

# Build Stages

`fleetctl` is built in stages, each with an exit criterion. Full detail: `docs/architecture.md` §14.

## Status

| # | Stage | Exit criterion | Status |
|---|-------|----------------|--------|
| **S0** | Repo bootstrap | CI green on an empty package | ✅ done |
| **S1** | Core kernel | `FakeTransport` + `LocalArtifactStore` run a trivial step end-to-end in tests, with audit records asserted | ✅ done |
| **S2** | First pack + first app | Parity: capture → build → deploy a real device, matching what `firestick_manager` produces | ⬜ next |
| **S3** | Config-as-code + workflows | `fleetctl run kodi-refresh --dry-run` prints a correct plan; `config show <device>` explains every key | ⬜ |
| **S4** | Policy + audit hardening | The gold device is structurally undeployable-to without a config edit | ⬜ |
| **S5** | Shield Pro | One workflow deploys the same Kodi build to a Stick and a Shield | ⬜ |
| **S6** | MCP adapter | An agent completes `kodi-refresh` with per-step approval, fully audited | ⬜ |
| **S7** | HA cutover | Live panel runs on `fleetctl`; `firestick_manager` archived | ⬜ |
| **S8** | Later | `linux_host` + SSH; HTTP API if a consumer appears; `fleet.lock` | ⬜ |

## Six decisions that were open before S1 — five now settled

Full detail in `docs/architecture.md` §14 ("Open before S1").

| # | Decision | Outcome |
|---|---|---|
| 1 | `Transport.exec()` effect parameter | ✅ every mutating entry point takes `effect`, defaulting to `MUTATING` (fail-safe) |
| 2 | Split `StepContext` by step kind | ✅ `FleetStepContext` / `DeviceStepContext` / `TransformStepContext` |
| 3 | The app↔pack contract | ✅ `state` is the deep verb — the pack owns paths, archives, staging and free space; an app pack issues no transfer command |
| 4 | Config layering earlier than S3 | ✅ landed in S1 (`core/config/layering.py`) |
| 5 | Enforce the ring rule in CI | ✅ `tests/test_architecture.py`, part of the gate |
| 6 | `Step` returns `StepResult` | ✅ carries `summary`, `artifacts`, `facts` |

All six are settled. Decision 3 resolved in favour of the deep `state` verb: an app declares an `AppStateSpec` (its platform identifiers, state subdirectory, members, exclusions) and the device pack resolves the path, builds the archive with whatever tooling actually works on that hardware, checks headroom, and verifies the result. This is what keeps `apps/kodi` from encoding the toybox `tar -z` quirk that a Shield must not inherit.

## Ordering rules

1. **S1 before everything.** Both `ArtifactStore` adapters land in S1 — the local one is what makes S2 testable at all.
2. **S4 before S6.** Policy and audit precede MCP. This is the only ordering in the plan that is hard to walk back: agent-facing tools over a fleet with no policy layer and no audit record.
3. **S2 is the honesty gate.** Parity against real hardware before any of the interesting work.
4. **S5 validates the design.** If adding the Shield requires touching `core/` or `apps/kodi/`, the seams are wrong — stop and fix rather than working around.
5. **S7 is a two-repo coordinated release** with its own deploy quirks (manual manifest bump, `scp`, restart, on a feature branch not `main`).

## Scope discipline

Do not build ahead of the current stage. Concretely:

- No empty `core/` subpackages with stub `__init__.py` files "ready for later."
- No abstraction whose second adapter does not exist yet in the same stage.
- No policy hooks before S4; no MCP surface before S6.

The architecture doc describes the destination. The stage table describes what is allowed to exist right now.

## Carried forward from `firestick_manager`

Hard-won behaviour that must survive the port intact (S2/S5). Each has a memory entry:

| Behaviour | Lands in |
|-----------|----------|
| Netcat upload; listener cannot be backgrounded; md5 tail check | `AdbTransport.put()` |
| `tar cf` + separate `gzip`, never `tar czf` | `packs/firetv` quirk |
| Flat build archives (no `.kodi/` wrapper) | `apps/kodi` build |
| Single-archive transfer, never per-file sync | `apps/kodi` deploy |
| Size-scaled timeouts for transfer and unpack | `AdbTransport` |
| Working cancellation, debounced flush, restart handling | `core/operations` |
| MAC → serial → IP reconciliation; only overwrite on a real value | `core/inventory` |
| Gold device protection | `core/policy` (S4), as config — not a convention |
