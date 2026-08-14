# fleetctl

Plugin-based fleet management for home devices — Fire TV sticks, NVIDIA Shields, PCs — and the software running on them. Entry point is `fleetctl` (`src/fleetctl/cli.py`), run via `uv run fleetctl ...`.

**Pre-alpha.** Built in stages; nothing manages a real device yet. See `.claude/skills/build-stages/SKILL.md` for what is in scope right now, and refuse to build ahead of the current stage.

See `.claude/` for the deep reference: agents (`core-kernel-specialist`, `pack-author`), skills (architecture, build stages, pack authoring, ADB device ops, Kodi app ops, live device runs), commands (`/gate`, `/stage`, `/pack-new`, `/ring-check`), and rules per ring. Full design rationale: `docs/architecture.md`.

## Setup

```bash
uv sync --all-extras
uv run pytest
uv run fleetctl --version
```

## The three rings

| Ring | Knows about | May import |
|------|-------------|------------|
| `core/` | nothing device- or app-specific | stdlib + third-party only |
| `packs/` | what a device *is* (`firetv`, `shield`, `linux_host`) | `core/` |
| `apps/` | software *on* a device (`kodi`) | `core/` |

**Dependencies point inward only.** `apps/` never imports `packs/` — it declares the capabilities it needs (`files.push`, `exec`, `state.restore`) and the engine resolves which pack provides them. That indirection is the entire reason one Kodi build can deploy to a Fire Stick and a Shield without either knowing the other exists. `/ring-check` verifies this.

## Non-negotiables

- **A seam ships with two adapters** or it is hypothetical. The second is usually the test double (`FakeTransport`, `LocalArtifactStore`, `InMemoryAuditSink`).
- **Every step declares an effect class** — `READ` / `MUTATING` / `DESTRUCTIVE`. The policy layer keys off it, so a mislabelled destructive step silently bypasses approval. Highest-consequence declaration in the codebase.
- **Vendor quirks belong to the pack that has them, as data.** `pm disable-user` no-oping and toybox `tar -z` truncating are *Amazon's* bugs, not Android's — the Shield must not inherit them. Compose `packs/android`; never subclass a vendor pack.
- **Transforms go in `build`, never `deploy`.** Structurally enforced: `build` gets a transform chain and no transport; `deploy` gets a transport and no transform chain.
- **Nothing constructs its own dependencies.** Construction happens only in a composition root (`cli/bootstrap.py`, the HA setup, `tests/conftest.py`).
- **No test touches real hardware, a real network, or a real SMB share.** If something can only be tested against a device, the seam is wrong.

## Quality gate

```bash
uv run black src tests && uv run isort src tests
uv run mypy                                   # strict; must stay clean
uv run pytest --cov=src --cov-report=term-missing
```

CI runs exactly this on Python 3.12 and 3.13. `/gate` does it and fixes what it finds.

## Memory is local; the repo gets artifacts

`.claude/memory/` is gitignored and stays that way. It is a curation surface an agent writes to
unsupervised — tracking it would put an unreviewed write target inside the commit surface, in a repo
whose central risk is real device data reaching a public commit.

So memory is never the deliverable. When something in it proves durable, **write it into the artifact
that owns it** and commit that:

| Kind of fact | Where it lands |
|---|---|
| Hardware or vendor behaviour | the pack's `data/*.yml`, or `adb-device-ops` / `live-device-runs` skill |
| A rule about where code goes | `.claude/rules/`, or the `fleetctl-architecture` skill |
| A procedure with steps | a command (`/gate`, `/pack-new`) or a skill |
| A standing constraint on all work here | this file |
| Stage scope and exit criteria | the `build-stages` skill |

A committed file must never cite a memory filename — that reference dangles for anyone who clones.
Inline the fact instead.

## Credentials and real device data — never commit

`config/` is gitignored except `*.example`; so are `.env`, `.adb_keys/`, and runtime `logs/`/`audit/`/`staging/`.

Config files hold secret **references** (`!ref env:NAME`), never values — resolved at the edge per consumer (HA config entry, environment, OS keyring). A `fleet.yml` must stay safe to paste into a bug report.

**This ships publicly.** No real IPs, MAC addresses, hostnames, serials, or credentials anywhere — code, tests, docs, comments, fixtures. Use `192.168.1.50` and `aa:bb:cc:dd:ee:ff`. This exact failure happened in the predecessor project: real device data reached a committed doc and needed a history rewrite to scrub. Before committing anything under `.claude/`, `docs/`, or `tests/`, grep for MAC- and credential-shaped patterns if real device data could plausibly have been referenced.

## Predecessor

`firestick_manager` was the predecessor and the source of truth for **hardware behaviour**, not
architecture. **Retired 2026-08-06 (S7 cutover)** — it no longer runs and is no longer a sibling
directory. It was moved rather than deleted, because it held gitignored real device data that git
history alone would not have preserved, so treat it as **readable but dead**: do not cite its paths,
skills, or agents as live, do not repin anything to it, and never copy a value out of its gitignored
files into anything committed here.

Everything worth keeping was ported and now lives in this repo — netcat upload, `tar cf` plus a
separate `gzip`, flat build archives, single-archive transfer, size-scaled timeouts, the operation
registry, and serial → MAC → address reconciliation. If a behaviour question is not already answered
by a skill or the code, it was **not** ported: treat it as a gap to reimplement and verify against
real hardware. Reading the archive is a last resort, and nothing read there is authoritative until
re-verified on a device.
