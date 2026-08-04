---
name: Dev commands never build a wheel, so packaging breaks go unnoticed
description: v0.1.0 was tagged with a pyproject force-include that made hatchling fail outright; nothing in the local loop builds a wheel, so it was only caught when Home Assistant tried to pip-install it.
type: project
---

`pyproject.toml` carried `[tool.hatch.build.targets.wheel.force-include]` mapping `src/fleetctl/packs` → `fleetctl/packs`, left over from S2. But `packages = ["src/fleetctl"]` already includes `packs/` recursively, so hatchling saw the same destination twice and raised `ValueError: A second file is being added to the wheel archive at the same path: fleetctl/packs/__init__.py`. The wheel could not build at all.

Every local command — `pytest`, `mypy`, `uv run fleetctl` — runs against the **editable source tree** and never exercises the wheel build. `uv build` was not part of any loop, so a package that was 100% uninstallable passed a fully green quality gate and got tagged v0.1.0. It surfaced only when Home Assistant tried `pip install fleetctl @ git+...@v0.1.0`, the build failed, and the whole `firetools` integration went down with "Invalid config".

**Why:** a green test suite says nothing about whether the artifact you ship can be installed. The gate covered correctness but not distributability.

**How to apply:** before tagging a release, actually build and install into a throwaway venv, then import the top-level subpackages:

```bash
uv build
python -m venv /tmp/t && /tmp/t/Scripts/python -m pip install dist/fleetctl-*.whl
/tmp/t/Scripts/python -c "import fleetctl.packs, fleetctl.apps.kodi, fleetctl.agent.toolkit"
python -m zipfile -l dist/fleetctl-*.whl | grep -E "data/.*\.yml"   # shipped YAML is easy to lose
```

Trusting `uv build` to exit 0 is not enough — verify the wheel's *contents* and that it imports. v0.1.0 was deleted upstream and v0.1.1 is the first genuinely installable tag.
