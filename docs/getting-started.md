<h1 style="margin: 0 0 8px 0; padding: 0; border: 0; font-size: 2em;">Getting Started</h1>
<div style="color: #64748b; font-size: 15px; margin: 0 0 16px 0;">Clone, install, configure, and run fleetctl against a real device.</div>

<hr style="border: 0; border-top: 2px solid #005288; margin: 0 0 32px 0;"/>

<sub style="color: #64748b;">Last verified 2026-08-02</sub>

<blockquote style="border-left: 4px solid #fa9441; background-color: rgba(250, 148, 65, 0.08); padding: 14px 18px; margin: 16px 0; border-radius: 10px;">

**Status: S0–S6 done, S7 (Home Assistant cutover) not started.** `fleetctl` discovers devices, captures and rebuilds Kodi profiles, and deploys them over ADB — against real hardware, not just tests. What's missing is a production consumer: [`ha-parity.md`](ha-parity.md) is the map for that.

</blockquote>

<h2 style="border-left: 6px solid #005288; padding: 4px 0 10px 16px; margin: 40px 0 16px; border-bottom: 1px solid rgba(0, 82, 136, 0.25); background-image: url(data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20width%3D%27100%25%27%20height%3D%27100%25%27%3E%3Cdefs%3E%3Cpattern%20id%3D%27h%27%20width%3D%2720%27%20height%3D%2735%27%20patternUnits%3D%27userSpaceOnUse%27%3E%3Cpath%20d%3D%27M10%2023L0%2018V6L10%200l10%206v12L10%2023zm0%200v12%27%20fill%3D%27none%27%20stroke%3D%27%23005288%27%20stroke-opacity%3D%270.22%27%2F%3E%3C%2Fpattern%3E%3ClinearGradient%20id%3D%27lg%27%20x1%3D%270%25%27%20x2%3D%27100%25%27%3E%3Cstop%20offset%3D%270%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%271%27%2F%3E%3Cstop%20offset%3D%2785%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%270%27%2F%3E%3C%2FlinearGradient%3E%3Cmask%20id%3D%27f%27%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23lg%29%27%2F%3E%3C%2Fmask%3E%3C%2Fdefs%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23h%29%27%20mask%3D%27url%28%23f%29%27%2F%3E%3C%2Fsvg%3E); background-size: 100% 100%; background-repeat: no-repeat; border-radius: 3px;">Prerequisites</h2>

- Python 3.12 or 3.13
- [uv](https://docs.astral.sh/uv/) — this project uses uv exclusively; there's no `requirements.txt`, no Poetry, no bare `pip install`
- A Fire TV or NVIDIA Shield with ADB debugging enabled, if you want to point it at a real device
- An SMB share, if you want artifacts to live off your machine — optional; local storage under `~/.fleetctl/artifacts` works with no config

<h2 style="border-left: 6px solid #005288; padding: 4px 0 10px 16px; margin: 40px 0 16px; border-bottom: 1px solid rgba(0, 82, 136, 0.25); background-image: url(data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20width%3D%27100%25%27%20height%3D%27100%25%27%3E%3Cdefs%3E%3Cpattern%20id%3D%27h%27%20width%3D%2720%27%20height%3D%2735%27%20patternUnits%3D%27userSpaceOnUse%27%3E%3Cpath%20d%3D%27M10%2023L0%2018V6L10%200l10%206v12L10%2023zm0%200v12%27%20fill%3D%27none%27%20stroke%3D%27%23005288%27%20stroke-opacity%3D%270.22%27%2F%3E%3C%2Fpattern%3E%3ClinearGradient%20id%3D%27lg%27%20x1%3D%270%25%27%20x2%3D%27100%25%27%3E%3Cstop%20offset%3D%270%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%271%27%2F%3E%3Cstop%20offset%3D%2785%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%270%27%2F%3E%3C%2FlinearGradient%3E%3Cmask%20id%3D%27f%27%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23lg%29%27%2F%3E%3C%2Fmask%3E%3C%2Fdefs%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23h%29%27%20mask%3D%27url%28%23f%29%27%2F%3E%3C%2Fsvg%3E); background-size: 100% 100%; background-repeat: no-repeat; border-radius: 3px;">Clone and install</h2>

<div align="left" style="margin-bottom: -16px;"><img src="assets/lang-bash.svg" height="18"/></div>

```bash
git clone https://github.com/salvuswarez/fleetctl.git
cd fleetctl
uv sync --all-extras
```

`uv sync --all-extras` creates `.venv/` and installs the package plus the `dev` and `mcp` dependency groups defined in `pyproject.toml`.

<h2 style="border-left: 6px solid #005288; padding: 4px 0 10px 16px; margin: 40px 0 16px; border-bottom: 1px solid rgba(0, 82, 136, 0.25); background-image: url(data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20width%3D%27100%25%27%20height%3D%27100%25%27%3E%3Cdefs%3E%3Cpattern%20id%3D%27h%27%20width%3D%2720%27%20height%3D%2735%27%20patternUnits%3D%27userSpaceOnUse%27%3E%3Cpath%20d%3D%27M10%2023L0%2018V6L10%200l10%206v12L10%2023zm0%200v12%27%20fill%3D%27none%27%20stroke%3D%27%23005288%27%20stroke-opacity%3D%270.22%27%2F%3E%3C%2Fpattern%3E%3ClinearGradient%20id%3D%27lg%27%20x1%3D%270%25%27%20x2%3D%27100%25%27%3E%3Cstop%20offset%3D%270%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%271%27%2F%3E%3Cstop%20offset%3D%2785%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%270%27%2F%3E%3C%2FlinearGradient%3E%3Cmask%20id%3D%27f%27%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23lg%29%27%2F%3E%3C%2Fmask%3E%3C%2Fdefs%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23h%29%27%20mask%3D%27url%28%23f%29%27%2F%3E%3C%2Fsvg%3E); background-size: 100% 100%; background-repeat: no-repeat; border-radius: 3px;">Confirm it's installed</h2>

<div align="left" style="margin-bottom: -16px;"><img src="assets/lang-bash.svg" height="18"/></div>

```bash
uv run fleetctl --version
uv run fleetctl --help
```

`--help` lists the ten commands: `scan`, `run`, `workflow`, `devices`, `config`, `steps`, `packs`, `artifacts`, `audit`, `mcp`. Full reference: [`cli-reference.md`](cli-reference.md).

<h2 style="border-left: 6px solid #005288; padding: 4px 0 10px 16px; margin: 40px 0 16px; border-bottom: 1px solid rgba(0, 82, 136, 0.25); background-image: url(data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20width%3D%27100%25%27%20height%3D%27100%25%27%3E%3Cdefs%3E%3Cpattern%20id%3D%27h%27%20width%3D%2720%27%20height%3D%2735%27%20patternUnits%3D%27userSpaceOnUse%27%3E%3Cpath%20d%3D%27M10%2023L0%2018V6L10%200l10%206v12L10%2023zm0%200v12%27%20fill%3D%27none%27%20stroke%3D%27%23005288%27%20stroke-opacity%3D%270.22%27%2F%3E%3C%2Fpattern%3E%3ClinearGradient%20id%3D%27lg%27%20x1%3D%270%25%27%20x2%3D%27100%25%27%3E%3Cstop%20offset%3D%270%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%271%27%2F%3E%3Cstop%20offset%3D%2785%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%270%27%2F%3E%3C%2FlinearGradient%3E%3Cmask%20id%3D%27f%27%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23lg%29%27%2F%3E%3C%2Fmask%3E%3C%2Fdefs%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23h%29%27%20mask%3D%27url%28%23f%29%27%2F%3E%3C%2Fsvg%3E); background-size: 100% 100%; background-repeat: no-repeat; border-radius: 3px;">First-run setup</h2>

Nothing runs against a device until there is somewhere to record what a scan finds, and — optionally — somewhere to put artifacts other than your local disk.

<div align="left" style="margin-bottom: -16px;"><img src="assets/lang-bash.svg" height="18"/></div>

```bash
cp config/fleet.yml.example config/fleet.yml
cp .env.example .env
```

Edit `.env` if you have an SMB share (fills `!ref env:SMB_USER` / `!ref env:SMB_PASS` in `fleet.yml`); leave `fleet.yml`'s `artifacts.smb` block out entirely to store captures and builds under `~/.fleetctl/artifacts` instead. `config/inventory/devices.yml` does not need creating by hand — the first scan writes it. See [`configuration.md`](configuration.md) for every field in both files.

Both `.env` and `config/inventory/devices.yml` are gitignored: real credentials and real device MAC/IP data never get committed. The `.example` files are the tracked reference.

<h2 style="border-left: 6px solid #005288; padding: 4px 0 10px 16px; margin: 40px 0 16px; border-bottom: 1px solid rgba(0, 82, 136, 0.25); background-image: url(data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20width%3D%27100%25%27%20height%3D%27100%25%27%3E%3Cdefs%3E%3Cpattern%20id%3D%27h%27%20width%3D%2720%27%20height%3D%2735%27%20patternUnits%3D%27userSpaceOnUse%27%3E%3Cpath%20d%3D%27M10%2023L0%2018V6L10%200l10%206v12L10%2023zm0%200v12%27%20fill%3D%27none%27%20stroke%3D%27%23005288%27%20stroke-opacity%3D%270.22%27%2F%3E%3C%2Fpattern%3E%3ClinearGradient%20id%3D%27lg%27%20x1%3D%270%25%27%20x2%3D%27100%25%27%3E%3Cstop%20offset%3D%270%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%271%27%2F%3E%3Cstop%20offset%3D%2785%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%270%27%2F%3E%3C%2FlinearGradient%3E%3Cmask%20id%3D%27f%27%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23lg%29%27%2F%3E%3C%2Fmask%3E%3C%2Fdefs%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23h%29%27%20mask%3D%27url%28%23f%29%27%2F%3E%3C%2Fsvg%3E); background-size: 100% 100%; background-repeat: no-repeat; border-radius: 3px;">Find your devices</h2>

<div align="left" style="margin-bottom: -16px;"><img src="assets/lang-bash.svg" height="18"/></div>

```bash
uv run fleetctl scan 192.168.1.0/24
```

Sweeps the subnet, identifies anything an installed pack (`firetv`, `shield`) recognizes, and merges it into `config/inventory/devices.yml`. Add `--dry-run` to see what would be found without writing anything. A device that's reachable but refuses the ADB key is recorded too, flagged `unauthorized` rather than dropped — approve the on-device debugging prompt and scan again.

Scan never touches `tags` or `vars` on a device it already knows — those are yours to hand-edit. Tag a device `kodi` to bring it into the shipped Kodi workflows; tag your reference device `gold` as well, since `kodi-capture-gold` targets that tag.

<div align="left" style="margin-bottom: -16px;"><img src="assets/lang-yaml.svg" height="18"/></div>

```yaml
# config/inventory/devices.yml
devices:
  - id: living-room-stick
    type: firetv
    address: 192.168.1.50
    tags: [kodi, gold]
    vars: {}
```

<h2 style="border-left: 6px solid #005288; padding: 4px 0 10px 16px; margin: 40px 0 16px; border-bottom: 1px solid rgba(0, 82, 136, 0.25); background-image: url(data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20width%3D%27100%25%27%20height%3D%27100%25%27%3E%3Cdefs%3E%3Cpattern%20id%3D%27h%27%20width%3D%2720%27%20height%3D%2735%27%20patternUnits%3D%27userSpaceOnUse%27%3E%3Cpath%20d%3D%27M10%2023L0%2018V6L10%200l10%206v12L10%2023zm0%200v12%27%20fill%3D%27none%27%20stroke%3D%27%23005288%27%20stroke-opacity%3D%270.22%27%2F%3E%3C%2Fpattern%3E%3ClinearGradient%20id%3D%27lg%27%20x1%3D%270%25%27%20x2%3D%27100%25%27%3E%3Cstop%20offset%3D%270%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%271%27%2F%3E%3Cstop%20offset%3D%2785%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%270%27%2F%3E%3C%2FlinearGradient%3E%3Cmask%20id%3D%27f%27%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23lg%29%27%2F%3E%3C%2Fmask%3E%3C%2Fdefs%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23h%29%27%20mask%3D%27url%28%23f%29%27%2F%3E%3C%2Fsvg%3E); background-size: 100% 100%; background-repeat: no-repeat; border-radius: 3px;">Plan, then run</h2>

Every mutating workflow needs a plan reviewed before it runs — the plan's digest has to match what you pass to `--confirm`, so a workflow can't be run against a fleet that changed since you looked at it.

<div align="left" style="margin-bottom: -16px;"><img src="assets/lang-bash.svg" height="18"/></div>

```bash
uv run fleetctl workflow plan kodi-check
uv run fleetctl workflow run kodi-check --confirm <digest-from-plan>
```

`kodi-check` is read-only and needs no approval under any policy — a safe first run. To see everything shipped: `uv run fleetctl workflow list`. A single step, outside a workflow, runs directly:

<div align="left" style="margin-bottom: -16px;"><img src="assets/lang-bash.svg" height="18"/></div>

```bash
uv run fleetctl run firetv.check --device living-room-stick
```

<h2 style="border-left: 6px solid #005288; padding: 4px 0 10px 16px; margin: 40px 0 16px; border-bottom: 1px solid rgba(0, 82, 136, 0.25); background-image: url(data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20width%3D%27100%25%27%20height%3D%27100%25%27%3E%3Cdefs%3E%3Cpattern%20id%3D%27h%27%20width%3D%2720%27%20height%3D%2735%27%20patternUnits%3D%27userSpaceOnUse%27%3E%3Cpath%20d%3D%27M10%2023L0%2018V6L10%200l10%206v12L10%2023zm0%200v12%27%20fill%3D%27none%27%20stroke%3D%27%23005288%27%20stroke-opacity%3D%270.22%27%2F%3E%3C%2Fpattern%3E%3ClinearGradient%20id%3D%27lg%27%20x1%3D%270%25%27%20x2%3D%27100%25%27%3E%3Cstop%20offset%3D%270%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%271%27%2F%3E%3Cstop%20offset%3D%2785%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%270%27%2F%3E%3C%2FlinearGradient%3E%3Cmask%20id%3D%27f%27%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23lg%29%27%2F%3E%3C%2Fmask%3E%3C%2Fdefs%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23h%29%27%20mask%3D%27url%28%23f%29%27%2F%3E%3C%2Fsvg%3E); background-size: 100% 100%; background-repeat: no-repeat; border-radius: 3px;">Run the tests</h2>

<div align="left" style="margin-bottom: -16px;"><img src="assets/lang-bash.svg" height="18"/></div>

```bash
uv run pytest
```

500 tests, weighted toward the failure modes that bit the predecessor project on real hardware. For coverage:

<div align="left" style="margin-bottom: -16px;"><img src="assets/lang-bash.svg" height="18"/></div>

```bash
uv run pytest --cov=src --cov-report=term-missing
```

The gate requires 90% and currently sits around 90.6%.

<h2 style="border-left: 6px solid #005288; padding: 4px 0 10px 16px; margin: 40px 0 16px; border-bottom: 1px solid rgba(0, 82, 136, 0.25); background-image: url(data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20width%3D%27100%25%27%20height%3D%27100%25%27%3E%3Cdefs%3E%3Cpattern%20id%3D%27h%27%20width%3D%2720%27%20height%3D%2735%27%20patternUnits%3D%27userSpaceOnUse%27%3E%3Cpath%20d%3D%27M10%2023L0%2018V6L10%200l10%206v12L10%2023zm0%200v12%27%20fill%3D%27none%27%20stroke%3D%27%23005288%27%20stroke-opacity%3D%270.22%27%2F%3E%3C%2Fpattern%3E%3ClinearGradient%20id%3D%27lg%27%20x1%3D%270%25%27%20x2%3D%27100%25%27%3E%3Cstop%20offset%3D%270%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%271%27%2F%3E%3Cstop%20offset%3D%2785%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%270%27%2F%3E%3C%2FlinearGradient%3E%3Cmask%20id%3D%27f%27%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23lg%29%27%2F%3E%3C%2Fmask%3E%3C%2Fdefs%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23h%29%27%20mask%3D%27url%28%23f%29%27%2F%3E%3C%2Fsvg%3E); background-size: 100% 100%; background-repeat: no-repeat; border-radius: 3px;">Run the quality gate</h2>

Every pull request runs the same four checks CI runs, on Python 3.12 and 3.13:

<div align="left" style="margin-bottom: -16px;"><img src="assets/lang-bash.svg" height="18"/></div>

```bash
uv run black src tests --check
uv run isort src tests --check-only
uv run mypy
uv run pytest --cov=src --cov-report=term-missing
```

Drop `--check`/`--check-only` to have `black`/`isort` fix formatting in place rather than just report on it. `mypy` runs in `strict` mode against both `src` and `tests` and must stay clean.

<div align="left" style="margin-bottom: -16px;"><img src="assets/lang-bash.svg" height="18"/></div>

```bash
uv build   # wheel + sdist to dist/, if you want to check packaging
```

<h2 style="border-left: 6px solid #005288; padding: 4px 0 10px 16px; margin: 40px 0 16px; border-bottom: 1px solid rgba(0, 82, 136, 0.25); background-image: url(data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20width%3D%27100%25%27%20height%3D%27100%25%27%3E%3Cdefs%3E%3Cpattern%20id%3D%27h%27%20width%3D%2720%27%20height%3D%2735%27%20patternUnits%3D%27userSpaceOnUse%27%3E%3Cpath%20d%3D%27M10%2023L0%2018V6L10%200l10%206v12L10%2023zm0%200v12%27%20fill%3D%27none%27%20stroke%3D%27%23005288%27%20stroke-opacity%3D%270.22%27%2F%3E%3C%2Fpattern%3E%3ClinearGradient%20id%3D%27lg%27%20x1%3D%270%25%27%20x2%3D%27100%25%27%3E%3Cstop%20offset%3D%270%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%271%27%2F%3E%3Cstop%20offset%3D%2785%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%270%27%2F%3E%3C%2FlinearGradient%3E%3Cmask%20id%3D%27f%27%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23lg%29%27%2F%3E%3C%2Fmask%3E%3C%2Fdefs%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23h%29%27%20mask%3D%27url%28%23f%29%27%2F%3E%3C%2Fsvg%3E); background-size: 100% 100%; background-repeat: no-repeat; border-radius: 3px;">Repo layout tour</h2>

```text
fleetctl/
├── src/fleetctl/
│   ├── core/                 # device-agnostic kernel — the only ring apps/packs may not skip
│   │   ├── transport/        # Transport protocol, AdbTransport, netcat push
│   │   ├── artifacts/        # ArtifactStore protocol: SMB + local backends
│   │   ├── config/           # fleet.yml loading, !ref secrets, .env, layered resolution
│   │   ├── discovery/        # subnet sweep, pack claiming, the fleet.scan step
│   │   ├── inventory/        # devices.yml read/write/reconcile
│   │   ├── operations/       # operation tracking, one-per-device guard, background dispatch
│   │   ├── observability/    # diagnostics / timeline / audit — three streams
│   │   ├── workflow/         # Workflow, engine, plan/dry-run, the step runner
│   │   └── policy.py         # per-actor allow/confirm/deny, protected devices
│   ├── packs/                # what a device *is*: firetv, shield (both compose packs/android)
│   ├── apps/kodi/            # software *on* a device: capture/build/deploy, recipes as YAML
│   ├── agent/toolkit.py      # the policy-aware surface MCP and a future HA integration call
│   ├── mcp/                  # MCP server exposing the toolkit over stdio
│   └── cli/                  # Click commands — a thin wrapper over the same step bodies
├── tests/                    # 500 tests, mirroring the src/ layout
├── config/
│   ├── fleet.yml.example     # SMB, observability, policy — copy to fleet.yml
│   └── inventory/devices.yml.example
├── docs/
│   ├── architecture.md       # design source of truth — 15 sections, 21 diagrams
│   ├── cli-reference.md      # every command and flag
│   ├── configuration.md      # fleet.yml, .env, devices.yml, every field
│   ├── pack-authoring.md     # the extension contract for a new device type
│   ├── safety.md             # policy, protected devices, plan-then-run, --approve
│   ├── observability.md      # diagnostics / timeline / audit
│   ├── roadmap.md            # S0–S8 stages, exit criteria, current status
│   └── ha-parity.md          # every Home Assistant panel command mapped to its fleetctl equivalent
├── .claude/                  # agents, skills, commands, per-ring rules
├── pyproject.toml
├── CLAUDE.md
├── README.md
├── SECURITY.md
└── CONTRIBUTING.md
```

<h2 style="border-left: 6px solid #005288; padding: 4px 0 10px 16px; margin: 40px 0 16px; border-bottom: 1px solid rgba(0, 82, 136, 0.25); background-image: url(data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20width%3D%27100%25%27%20height%3D%27100%25%27%3E%3Cdefs%3E%3Cpattern%20id%3D%27h%27%20width%3D%2720%27%20height%3D%2735%27%20patternUnits%3D%27userSpaceOnUse%27%3E%3Cpath%20d%3D%27M10%2023L0%2018V6L10%200l10%206v12L10%2023zm0%200v12%27%20fill%3D%27none%27%20stroke%3D%27%23005288%27%20stroke-opacity%3D%270.22%27%2F%3E%3C%2Fpattern%3E%3ClinearGradient%20id%3D%27lg%27%20x1%3D%270%25%27%20x2%3D%27100%25%27%3E%3Cstop%20offset%3D%270%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%271%27%2F%3E%3Cstop%20offset%3D%2785%25%27%20stop-color%3D%27white%27%20stop-opacity%3D%270%27%2F%3E%3C%2FlinearGradient%3E%3Cmask%20id%3D%27f%27%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23lg%29%27%2F%3E%3C%2Fmask%3E%3C%2Fdefs%3E%3Crect%20width%3D%27100%25%27%20height%3D%27100%25%27%20fill%3D%27url%28%23h%29%27%20mask%3D%27url%28%23f%29%27%2F%3E%3C%2Fsvg%3E); background-size: 100% 100%; background-repeat: no-repeat; border-radius: 3px;">Where to read next</h2>

- Every command and flag: [`cli-reference.md`](cli-reference.md)
- Every config field, `fleet.yml` through `devices.yml`: [`configuration.md`](configuration.md)
- The full design: [`architecture.md`](architecture.md)
- What's left before a real consumer can cut over: [`ha-parity.md`](ha-parity.md) and [`roadmap.md`](roadmap.md)
- Writing a new device pack: [`pack-authoring.md`](pack-authoring.md)
- The house rules for contributing: [`../CONTRIBUTING.md`](../CONTRIBUTING.md)
- The non-negotiables baked into the project's own `CLAUDE.md`: [`../CLAUDE.md`](../CLAUDE.md)

<br/><br/>

<hr style="border: 0; border-top: 1px solid rgba(100, 116, 139, 0.35); margin: 24px 0;"/>

<br/>

<table>
<tr>
<td width="22%" valign="top" align="center">

<br/>
<strong>fleetctl</strong>
<br/><br/>
<sub>Getting Started</sub>

</td>
<td width="26%" valign="top">

<h4><ins style="color: #2a8b93; text-decoration: none;">Documentation</ins></h4>

- [Getting Started](getting-started.md)
- [CLI Reference](cli-reference.md)
- [Configuration](configuration.md)
- [Architecture](architecture.md)
- [Safety & Policy](safety.md)

</td>
<td width="26%" valign="top">

<h4><ins style="color: #2a8b93; text-decoration: none;">Repositories</ins></h4>

- [fleetctl](https://github.com/salvuswarez/fleetctl)
- [firestick_manager](https://github.com/salvuswarez/firestick_manager) &mdash; predecessor
- [ha-cyberpunk](https://github.com/salvuswarez/ha-cyberpunk) &mdash; S7 consumer

<h4><ins style="color: #2a8b93; text-decoration: none;">References</ins></h4>

- [Observability](observability.md) &mdash; diagnostics, timeline, audit
- [Roadmap](roadmap.md) &mdash; S0&ndash;S8 stages
- [HA Parity](ha-parity.md) &mdash; panel command mapping

</td>
<td width="26%" valign="top">

<h4><ins style="color: #2a8b93; text-decoration: none;">About</ins></h4>

- Plugin-based home device fleet manager
- MIT licensed

<h4><ins style="color: #2a8b93; text-decoration: none;">Status</ins></h4>

- S0&ndash;S6 done &middot; S7 (HA cutover) not started

</td>
</tr>
</table>

<br/>

<hr style="border: 0; border-top: 1px solid rgba(100, 116, 139, 0.35); margin: 24px 0;"/>

<div align="center">
  <sub>fleetctl</sub>
</div>
