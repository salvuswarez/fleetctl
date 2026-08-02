# Getting started

> [!IMPORTANT]
> **Status: pre-alpha (S0 complete).** This document only describes what genuinely works today. There is no transport, no device pack, no app pack, and no config loader — `fleetctl` cannot point at a device, a network, or an SMB share yet. If you're looking for what's coming, see [`roadmap.md`](roadmap.md); if you're looking for the design, see [`architecture.md`](architecture.md).

## What you can actually do right now

Clone the repo, install it, run its (small) test suite, and run the quality gate. That's it — there is no `fleetctl scan`, no `fleetctl deploy`, no config file to write. The package today is a Click group with a `--version` flag and a `-v/--verbose` flag, backed by six tests.

## Prerequisites

- Python 3.12 or 3.13
- [uv](https://docs.astral.sh/uv/) — this project uses uv exclusively; there's no `requirements.txt`, no Poetry, no bare `pip install`

## Clone and install

```bash
git clone https://github.com/salvuswarez/fleetctl.git
cd fleetctl
uv sync --all-extras
```

`uv sync --all-extras` creates `.venv/` and installs the package plus the `dev` dependency group (`black`, `isort`, `mypy`, `pytest`, `pytest-cov`) defined in `pyproject.toml`.

## Confirm it's installed

```bash
uv run fleetctl --version
uv run fleetctl --help
```

The `--help` output is `Manage a fleet of home devices.` followed by no subcommands — the CLI group itself is the entire surface at this stage.

## Run the tests

```bash
uv run pytest
```

`tests/test_cli.py` covers exactly the surface described above: the `--version` flag reports the installed version, `--help` prints the group description, and `configure_logging()` maps `-v` repetition to the right logging level (`WARNING` at 0, `INFO` at 1, `DEBUG` at 2+).

For coverage:

```bash
uv run pytest --cov=src --cov-report=term-missing
```

## Run the quality gate

Every pull request runs the same four checks CI runs, on Python 3.12 and 3.13:

```bash
uv run black src tests --check
uv run isort src tests --check-only
uv run mypy
uv run pytest --cov=src --cov-report=term-missing
```

Drop `--check`/`--check-only` to have `black`/`isort` fix formatting in place rather than just report on it. `mypy` runs in `strict` mode against both `src` and `tests` (configured in `pyproject.toml`) and must stay clean — the predecessor project (`firestick_manager`) is strict-clean today, and this project starts from the same bar.

```bash
uv build   # wheel + sdist to dist/, if you want to check packaging
```

## Repo layout tour

```text
fleetctl/
├── src/fleetctl/
│   ├── __init__.py        # docstring only - no code, by house rule
│   └── cli.py              # Click group: --version, -v/--verbose, configure_logging()
├── tests/
│   └── test_cli.py         # the six tests covering the above
├── docs/
│   ├── architecture.md     # design source of truth — read this before writing code
│   ├── README.md            # this documentation set's index
│   ├── getting-started.md   # this file
│   ├── pack-authoring.md    # extension guide (planned S2+, written as the real contract)
│   ├── safety.md             # policy, protected devices, plan-then-run
│   ├── observability.md      # diagnostics / timeline / audit — three streams
│   └── roadmap.md            # S0–S8 stages, exit criteria, sequencing rules
├── .claude/
│   ├── agents/               # core-kernel-specialist, pack-author
│   ├── skills/                # architecture, build-stages, pack-authoring, adb-device-ops
│   └── commands/              # /gate, /stage, /pack-new, /ring-check
├── pyproject.toml
├── CLAUDE.md
├── README.md
├── SECURITY.md
└── CONTRIBUTING.md
```

Everything under `core/`, `packs/`, and `apps/` in the target layout (`docs/architecture.md` §3) does not exist in `src/fleetctl/` yet — those three rings are what S1–S5 build out, in that order.

## Where to read next

- The full design, before touching any code: [`architecture.md`](architecture.md)
- What each build stage contains and its exit criterion: [`roadmap.md`](roadmap.md)
- The house rules for contributing (formatting, docstrings, test conventions, what gets a PR sent back): [`../CONTRIBUTING.md`](../CONTRIBUTING.md)
- The non-negotiables baked into the project's own `CLAUDE.md`: [`../CLAUDE.md`](../CLAUDE.md)
