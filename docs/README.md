# Documentation index

`fleetctl` is a plugin-based fleet manager for home devices, built in stages. This directory is the reader-facing documentation set; `docs/architecture.md` is the design source of truth and everything else here links into it rather than repeating it.

> [!IMPORTANT]
> **Status: pre-alpha.** Only stage S0 (repo bootstrap) is complete. There is no transport, no pack, no app, no config loader, no workflow engine, no policy, no audit trail — none of it exists yet. Every doc below says explicitly what's real today versus what's planned. Don't take a code example as something you can currently run unless the doc says so.

## The documents

| Doc | For | What it covers |
|---|---|---|
| [`architecture.md`](architecture.md) | Anyone who wants the full design rationale | 15 sections, 21 diagrams: friction points in the predecessor, the three-ring target, config-as-code, workflows, observability, policy, MCP, the build plan, and every locked decision (§15) |
| [`getting-started.md`](getting-started.md) | A new contributor cloning the repo today | Clone, `uv sync`, run the tests, run the quality gate, tour the repo layout — honestly, there's nothing to point at a device yet |
| [`pack-authoring.md`](pack-authoring.md) | Anyone writing a device pack or app pack | The extension contract: probes, capability declarations, effect classes, composition over inheritance. Planned for S2+, written as the real contract now |
| [`safety.md`](safety.md) | Anyone who will eventually point this at real hardware | Effect classes, protected devices, per-actor policy, plan-then-run, blast-radius caps — cross-referenced against [`../SECURITY.md`](../SECURITY.md) |
| [`observability.md`](observability.md) | Anyone debugging a run or auditing what happened | The three separate streams (diagnostics, timeline, audit), why they're separate, and how correlation ids tie them together |
| [`roadmap.md`](roadmap.md) | Anyone deciding what to build next | Stages S0–S8, exit criteria, current status, and the sequencing rules that are hard to walk back |
| [`ha-parity.md`](ha-parity.md) | Anyone working on the Home Assistant cutover | All 21 panel commands mapped to their fleetctl equivalent, plus the behavioural differences the integration has to account for |

## What works today vs. what's planned

This table is the single fastest way to check whether something you're reading about actually exists yet. It mirrors `docs/architecture.md` §14 and `.claude/skills/build-stages/SKILL.md`, which is the canonical version — check there if this table and the code ever disagree.

| Stage | Contents | Status |
|---|---|---|
| **S0** | Repo bootstrap: `pyproject.toml`, `src/fleetctl/` skeleton, CI, licence | Done |
| **S1** | Core kernel: `Transport` protocol + `AdbTransport`, `ArtifactStore` (SMB + local), inventory, operations, secrets, observability | Not started |
| **S2** | First pack (`packs/firetv`) + first app (`apps/kodi`), capture → build → deploy parity with `firestick_manager` | Not started |
| **S3** | Config-as-code, layered resolution, workflow engine, plan/dry-run | Not started |
| **S4** | Policy engine, effect classification enforcement, protected devices, audit hash chain | Not started |
| **S5** | Shield Pro pack — validates the ring seams | Not started |
| **S6** | MCP adapter (stdio) | Not started |
| **S7** | Home Assistant cutover from `firestick_manager` | Not started |
| **S8** | `linux_host` + SSH transport, HTTP API if a consumer appears, `fleet.lock` | Not started |

Concretely, as of this writing: `src/fleetctl/__init__.py` exports `__version__`; `src/fleetctl/cli.py` is a Click group with `--version` and `-v/--verbose` and nothing else. Six tests cover that surface. That is the entire package.

## Where to read next

- New to the repo and want to run something → [`getting-started.md`](getting-started.md)
- Want the full design before writing any code → [`architecture.md`](architecture.md)
- Planning to add a device type or an app → [`pack-authoring.md`](pack-authoring.md), once S2 lands
- Concerned about what this tool can do to real hardware → [`safety.md`](safety.md) and [`../SECURITY.md`](../SECURITY.md)
- Wondering what's next or why the stages are ordered the way they are → [`roadmap.md`](roadmap.md)
