---
description: Scaffold a new device pack or app pack, wired to the right shared base and registered as an entry point.
argument-hint: "<device|app> <id>   (e.g. `device shield`)"
---

Scaffold a new device pack or app pack. Argument: `$ARGUMENTS` is `<device|app> <id>` (e.g. `device shield`).

1. **Check scope.** Confirm the pack is in scope for the current stage (`build-stages` skill) — refuse if it is building ahead. S8 is in progress and only its SSH slice has landed.
2. **Pick the shared base.** A device pack composes exactly one:
   - `packs/android` — anything reached over ADB (Fire OS, Android TV)
   - `packs/posix` — anything reached over SSH (Linux hosts, SteamOS handhelds)
   - neither, only if the device genuinely shares no transport with an existing base — say so explicitly and justify it.
   **Compose, never subclass a vendor pack.** Inheriting `firetv` would hand Amazon's bugs to the new device.
3. **Create the files.** A device pack is three things — there is no `probe.py` and no `actions.py`:
   ```
   src/fleetctl/packs/<id>/
   ├── __init__.py      # module docstring only — no re-exports, no __all__
   ├── pack.py          # class <Id>Pack — the probe, the capabilities, the steps
   └── data/*.yml       # package lists, prune paths, quirks, probe strings
   ```
   An app pack is `src/fleetctl/apps/<id>/` with `pack.py` exposing `<Id>App`; split further by concern only when it earns it (see `apps/kodi/`).
4. **Register the entry point** in `pyproject.toml`:
   ```toml
   [project.entry-points."fleetctl.packs"]
   <id> = "fleetctl.packs.<id>.pack:<Id>Pack"
   ```
   (or `[project.entry-points."fleetctl.apps"]` → `pack:<Id>App`). Then `uv sync` so the entry point is actually discoverable.
   **A shared base gets no entry point** — that is what makes it a base rather than a sibling, and `test_no_shared_base_is_registered_as_a_pack` fails if you register one.
5. **Write the probe.** It returns `None` for any host it does not recognize — never a partial identity, never an exception. Check claim ordering against the existing packs: a subnet sweep hits mostly non-devices, and the wrong pack claiming a host is worse than no pack claiming it. If the new pack overlaps an existing one (as `steamdeck` does with `linux_host`), make the *other* pack decline explicitly rather than relying on ordering luck.
6. **Declare capabilities honestly** and give every step an explicit effect class — `READ` / `MUTATING` / `DESTRUCTIVE`. Under-declare rather than over-declare. A mislabelled destructive step bypasses the policy layer entirely.
7. **Put the data in `data/*.yml`.** Package lists, prune paths and quirks are never Python constants. If supporting a second vendor would require editing Python, it is in the wrong place. No real IPs, MACs, hostnames, or serials — this repo ships publicly.
8. **Add tests** under `tests/unit/packs/test_<id>.py` (or `tests/unit/apps/`), against `FakeTransport` with canned command output. No test touches real hardware or a real network.
9. **Run `/gate`**, then `uv run pytest tests/unit/test_architecture.py` specifically — it asserts the ring rule, the sibling-import rule, and the shared-base-has-no-entry-point rule.
10. **Report what is verified vs inferred.** Say plainly whether the pack has been run against real hardware. `linux_host` is the cautionary example: registered, tested with fakes, never run against a plain Linux box.

Use the `pack-authoring` skill for the full template and checklist, `adb-device-ops` for Android hardware behaviour, and `live-device-runs` when you are ready to try it against a real device.
