Scaffold a new device pack or app pack. Argument: `$ARGUMENTS` is `<device|app> <id>` (e.g. `device shield`).

1. Confirm the pack is in scope for the current stage (`build-stages` skill) — refuse if it is building ahead.
2. Create `src/fleetctl/packs/<id>/` (or `apps/<id>/`) with `__init__.py` registration, `probe.py`, `actions.py`, and `data/`.
3. Register the entry point in `pyproject.toml` under `fleetctl.packs` / `fleetctl.apps`.
4. For a device pack: compose `packs/android` if it is Android-based — never subclass a vendor pack.
5. Declare capabilities honestly and give every step an explicit effect class.
6. Add tests against `FakeTransport` with canned command output.
7. Run `/gate`.

Use the `pack-authoring` skill for the full template and checklist, and `adb-device-ops` for hardware behaviour. Put package lists and quirks in `data/*.yml`, never in Python constants.
