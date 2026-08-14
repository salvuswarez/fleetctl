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
| **S2** | First pack + first app | Parity: capture → build → deploy a real device, matching what `firestick_manager` produces | ✅ done |
| **S3** | Config-as-code + workflows | `fleetctl workflow run kodi-refresh --dry-run` prints a correct plan; `config <device>` explains every key | ✅ done |
| **S4** | Policy + audit hardening | A device marked protected cannot be reached by any actor without a config edit | ✅ done |
| **S5** | Shield Pro | One workflow deploys the same Kodi build to a Stick and a Shield | ✅ done, **verified on hardware 2026-08-12** |
| **S6** | MCP adapter | An agent completes `kodi-refresh` with per-step approval, fully audited | ✅ done |
| **S7** | HA cutover | Live panel runs on `fleetctl`; `firestick_manager` archived | ✅ done (2026-08-06) |
| **S8** | Later | `linux_host` + SSH; HTTP API if a consumer appears; `fleet.lock` | 🟡 in progress — SSH slice only |

## S8 in progress — what has landed and what has not

S8 as written bundles three unrelated things. Only the first is started:

| Slice | Status |
|-------|--------|
| `packs/posix` (shared SSH base) + `packs/linux_host` + `packs/steamdeck` | ✅ verified on a Steam Deck |
| HTTP API | ⬜ not started, and conditional — only "if a consumer appears" |
| `fleet.lock` | ⬜ not started |

`packs/posix` is the second shared base after `packs/android`, so
`SHARED_PACKS` in `tests/unit/test_architecture.py` is a tuple. A shared base
must have **no entry point** — that is what makes it a base rather than a
sibling, and a test asserts it.

A Steam Deck is claimed by `packs/steamdeck`, not `linux_host`: SteamOS mounts
`/` read-only and keeps applications in Flatpak sandboxes, so `linux_host`
declines `ID=steamos` rather than applying its writable-root defaults.
`linux_host` itself declares neither `STATE` nor `APPS` and remains unverified
against a plain Linux box.

Capture, build, deploy, per-device config, maintenance and cache trimming all
run against the Deck, in both directions, on real hardware (2026-08-06,
SteamOS 3.8.24). Three facts from that run are worth carrying:

- **The Flatpak state root has no `.kodi` subdirectory.** Kodi's profile
  members sit directly in `~/.var/app/{identifier}/data`. The guess that it
  mirrored Android's `.kodi` was wrong, and would have written a profile into a
  directory Kodi does not read. This is why `AppStateSpec` carries
  `app_roots: Mapping[str, str]` per platform — android maps to `.kodi`, linux
  to `""`, and an absent entry legitimately means "no subdirectory".
- **A Deck needs `writable_root: false` and `use_sudo: false`.** `/` is
  read-only and `sudo -n` fails, so `linux_host` declines `ID=steamos` outright
  rather than applying its writable-root defaults.
- **The `gold` build carries exactly three compiled objects, all ELF ARM
  32-bit** — `inputstream.adaptive`, `inputstream.rtmp`, `pvr.iptvsimple`.
  Nothing else is architecture-specific. Deploying `gold` verbatim to an x86_64
  Deck would shadow the Flatpak's own working engines with unloadable ARM ones,
  which is what `deck.yml` (`extends: gold`) exists to prune.

## Six decisions that were open before S1 — five now settled

Full detail in `docs/architecture.md` §14 ("Open before S1").

| # | Decision | Outcome |
|---|---|---|
| 1 | `Transport.exec()` effect parameter | ✅ every mutating entry point takes `effect`, defaulting to `MUTATING` (fail-safe) |
| 2 | Split `StepContext` by step kind | ✅ `FleetStepContext` / `DeviceStepContext` / `TransformStepContext` |
| 3 | The app↔pack contract | ✅ `state` is the deep verb — the pack owns paths, archives, staging and free space; an app pack issues no transfer command |
| 4 | Config layering earlier than S3 | ✅ landed in S1 (`core/config/layering.py`) |
| 5 | Enforce the ring rule in CI | ✅ `tests/unit/test_architecture.py`, part of the gate |
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

Hard-won behaviour that must survive the port intact (S2/S5):

| Behaviour | Lands in |
|-----------|----------|
| Netcat upload; listener cannot be backgrounded; md5 tail check | `AdbTransport.put()` |
| `tar cf` + separate `gzip`, never `tar czf` | `packs/firetv` quirk |
| Flat build archives (no `.kodi/` wrapper) | `apps/kodi` build |
| Single-archive transfer, never per-file sync | `apps/kodi` deploy |
| Size-scaled timeouts for transfer and unpack | `AdbTransport` |
| Working cancellation, debounced flush, restart handling | `core/operations` |
| Serial → MAC → address reconciliation; only overwrite on a real value | `core/inventory` |
| Device protection (situational, not a standing rule) | `core/policy`, as opt-in config |
