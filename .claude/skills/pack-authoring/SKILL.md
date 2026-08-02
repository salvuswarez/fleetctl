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

## Common mistakes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Step runs against a device that can't support it | capability over-declared | declare only what's implemented |
| Agent runs a wipe without approval | effect class defaulted or wrong | mark it `DESTRUCTIVE` |
| Shield inherits a Fire OS workaround | subclassed a vendor pack | compose `packs/android` instead |
| A second vendor needs a code change | package list hardcoded | move it to `data/*.yml` |
| Scan drops a real device | probe raised instead of returning `None` | swallow transport errors in the probe |
| Two packs claim one host | probe priorities unset or equal | set `probe_priority` explicitly |
