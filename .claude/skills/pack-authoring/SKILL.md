---
name: pack-authoring
description: How to write a device pack or app pack — registration, probes, capabilities, effect classes, data files, and the tests each needs. Use when adding support for a new device type or a new application.
---

# Pack Authoring

A pack is a registered plugin. Adding one should require **zero changes in `core/`** — if it doesn't, raise it: the seam is in the wrong place.

## Device pack vs app pack

| | Device pack | App pack |
|---|---|---|
| Answers | what is this device, what can I do to it | how do I manage this software |
| Lives in | `packs/<id>/` | `apps/<id>/` |
| Declares | capabilities it provides | capabilities it requires |
| Registers via | `fleetctl.packs` entry point | `fleetctl.apps` entry point |
| Knows about the other? | no | no |

## Anatomy

```
packs/<id>/
├── __init__.py        # @device_pack registration
├── probe.py           # DeviceProbe — claim a host or return None
├── actions.py         # steps, each with effect class + params schema
└── data/
    ├── bloat.yml      # package lists — data, never Python constants
    └── quirks.yml     # vendor workarounds this device needs
```

## Registration

```python
@device_pack(
    id="firetv",
    transport="adb",
    capabilities={"reach", "facts", "exec", "files", "apps", "settings", "power", "state", "cleanup"},
    probe_priority=10,          # lower runs first; generic_net claims last
    data_dir="data",
)
class FireTvPack:
    ...
```

```toml
[project.entry-points."fleetctl.packs"]
firetv = "fleetctl.packs.firetv:FireTvPack"
```

## Probes

```python
def probe(self, host: ProbeContext) -> DeviceIdentity | None:
    manufacturer = host.exec_ok("getprop ro.product.manufacturer")
    if "Amazon" not in manufacturer:
        return None                       # not mine — let the next pack try
    return DeviceIdentity(type="firetv", model=..., serial=...)
```

Rules: return `None` (never a partial identity) when unrecognized; depend on `CommandRunner` only, not the full `Transport`; never raise on an unresponsive host — a subnet sweep hits mostly non-devices.

## Steps

```python
@step(
    id="firetv.maintain",
    summary="Disable bloatware, trim caches, and disable telemetry.",
    params=MaintainParams,                 # Pydantic model → CLI/HA/MCP schemas
    requires={"exec", "apps", "cleanup"},
    effect=Effect.DESTRUCTIVE,
)
def maintain(ctx: StepContext, params: MaintainParams) -> str:
    ...
```

One registration yields a Click command, an HA service schema, an MCP tool, and an HTTP route. Never hand-write those surfaces.

## Composition, not inheritance

`firetv` and `shield` both compose `packs/android`'s `AndroidActions`. Neither subclasses the other, and neither subclasses a base pack.

The reason is concrete: `pm disable-user` silently no-ops on Fire OS 5.x, and toybox `tar -z` truncates archives on that build. Those are **Amazon's bugs**, not Android's. Inheritance would hand them to the Shield along with a two-step tar that costs real time on a large profile.

## Checklist

- [ ] Capabilities declared honestly — under-declare rather than over-declare
- [ ] Every step declares its effect class (mislabelling bypasses policy)
- [ ] Package lists and prune paths in `data/*.yml`, not Python
- [ ] Vendor quirks scoped to this pack
- [ ] Probe returns `None` cleanly for foreign hosts
- [ ] No import of `core/` internals — only its public protocols
- [ ] No import of another pack (except `packs/android` as a composed collaborator)
- [ ] Tests run against `FakeTransport` with canned command output
- [ ] Docs state what was verified on real hardware vs. inferred

## Remote commands: what a green test cannot see

A `FakeTransport` is scripted, so it cannot tell you that the string you sent was wrong — only that
your parser handles the string you *expected*. Three failures live entirely in that gap, and all
three present as "the step said it worked and nothing changed".

- **A quoted `~` is a literal directory.** Quoting arguments is right — an unquoted path with a space
  deletes two directories — but it also stops the remote shell expanding `~`. `rm -rf '~/.cache/fleetctl'`
  targets a directory that does not exist, and `rm -rf` on a missing path exits 0. The same bite hit
  `df -k '~/...'`. `packs/posix/actions.py:expand_home()` resolves it via `echo $HOME` and **raises**
  when the home directory cannot be read, rather than acting on a path that is still wrong;
  `remove_paths` and `PosixStateManager` both go through it. Any `~`-relative value from a data file
  must be expanded before it reaches a quoted command, and tests must assert on the *expanded* path.
- **`pgrep -f <pattern>` matches its own shell.** `sh -c "pgrep -c -f kodi.bin"` contains the pattern,
  so the count is at least 1 whether or not the app is running — a false "still running", not an
  obvious error. Use the bracket trick (`'[k]odi.bin'`) or match the executable exactly (`pgrep -x`).
  This matters for any step that must confirm an app is stopped before editing its config, since Kodi
  rewrites `guisettings.xml` on exit and would genuinely clobber the edit. `flatpak ps` is not a
  substitute — it lists only what flatpak is tracking, so an app launched from a Steam shortcut is
  invisible to it.
- **A command that fails can read as one that worked.** The full version of this, and the verification
  patterns that survive it, are in `adb-device-ops`. `exec_ok` returning `""` on the POSIX side is the
  same shape: "the command does not exist" and "the answer is genuinely absent" arrive identically.

**Script a test double from output actually observed on the hardware**, never from an assumed CLI.
That is the only thing that catches any of the above.

## Common mistakes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Step runs against a device that can't support it | capability over-declared | declare only what's implemented |
| Space-reclaiming step frees nothing | `~` quoted into a literal path | `expand_home()` before quoting |
| App "still running" after a stop | bare `pgrep -f` matched itself | `pgrep -x`, or the `[k]` bracket trick |
| Agent runs a wipe without approval | effect class defaulted or wrong | mark it `DESTRUCTIVE` |
| Shield inherits a Fire OS workaround | subclassed a vendor pack | compose `packs/android` instead |
| A second vendor needs a code change | package list hardcoded | move it to `data/*.yml` |
| Scan drops a real device | probe raised instead of returning `None` | swallow transport errors in the probe |
| Two packs claim one host | probe priorities unset or equal | set `probe_priority` explicitly |
