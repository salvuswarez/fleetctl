---
name: fleetctl-architecture
description: The three-ring architecture (core/packs/apps), the seams, the dependency rules, and the vocabulary. Use when adding a module, deciding where code belongs, or reviewing whether something crossed a ring boundary.
---

# fleetctl Architecture Reference

Full design and rationale: `docs/architecture.md` (15 sections, 21 diagrams). This skill is the operational summary — what you need to place code correctly without re-reading 1,700 lines.

## The three rings

| Ring | Knows about | May import | Contents |
|------|-------------|------------|----------|
| `core/` | nothing device- or app-specific | stdlib + third-party only | transport, inventory, discovery, artifacts, operations, workflow, config, observability, registry |
| `packs/` | what a device *is* | `core/` | `android` and `posix` (shared bases, no entry point), `firetv`, `shield`, `linux_host`, `steamdeck` |
| `apps/` | software *on* a device | `core/` | `kodi` |

**Dependencies point inward only.** `apps/` never imports `packs/` — it declares capabilities and the engine resolves the provider. That indirection is the entire reason one Kodi build can target both a Fire Stick and a Shield.

## The seams

| Seam | Protocol | Adapters |
|------|----------|----------|
| Talk to a device | `Transport` (= `Reachable` + `CommandRunner` + `FileTransfer`) | `AdbTransport`, `SshTransport`, `FakeTransport`, `AuditingTransport` (decorator) |
| Store artifacts | `ArtifactStore` | `SmbArtifactStore`, `LocalArtifactStore` |
| Identify a host | `DevicePack.probe` on the pack protocol — there is no separate probe seam | one per device pack, ordered by `probe_priority` (low first) |
| Manage app state | `StateManager` | `AndroidStateManager`, `PosixStateManager` |
| Manage applications | `AppManager` | `AndroidAppManager`, `FlatpakAppManager` |
| Shape a profile | `ProfileTransform` | one per Kodi transform; pure |
| Record effects | `AuditSink` | `JsonlAuditSink`, `InMemoryAuditSink`, `ChainedAuditWriter` (fan-out) |
| Resolve a secret | `SecretResolver` + a provider | `EnvSecretProvider` (`core/config/secrets.py`) |

**Nothing claims last.** A host no pack recognizes is claimed by no pack — there is no
fallback. A probe that cannot identify a host returns `None`, never a partial identity.

**Rule:** a seam ships with two adapters or it is hypothetical. The second is usually the test double.

## The verb vocabulary

`reach` · `facts` · `exec` · `files` · `apps` · `settings` · `power` · `state` · `cleanup`

A pack declares which it supports; a step declares which it requires; the engine checks at **plan time**, before touching anything.

The nine split into two kinds, and the difference decides **who may answer for them**:

| Kind | Verbs | Authority |
|---|---|---|
| **Wire** | `reach` `facts` `exec` `files` `power` | the transport performs them directly |
| **Derived** | `state` `apps` `settings` `cleanup` | a pack's managers build them on the wire verbs |

`WIRE_CAPABILITIES` in `core/effects.py` names the first set. This stayed invisible while every
transport served exactly one pack, and broke the moment `SshTransport` served two: `kodi.capture` on
a Steam Deck was refused for "unsupported capabilities: state" even though the pack supplies a state
manager. The check is now `transport.capabilities() | (provided_by_pack - WIRE_CAPABILITIES)` — a pack
adds only what it implements and can never claim `exec` on a dead connection.

## Protection is anchored on inventory tags

The policy layer can mark a device protected against named steps, but it is **off by default**. Do
not protect a device by editing `fleet.yml`: the Home Assistant integration is a separate composition
root with its own `config_dir`, and it **regenerates** its `fleet.yml` from the config entry on every
setup, so a hand-added block is gone on the next reload. That is deliberate — the config entry is the
source of truth so an options-flow edit takes effect without hand-editing YAML.

Tag the device instead. `PROTECTED_TAGS` turns tags into `policy.protected` rules on every setup:
`gold` denies `kodi.deploy` and `*.maintain` while still allowing `kodi.capture` — capturing *from*
the gold source is the entire point — and `protected` denies everything. Tags are the right anchor
because `inventory/devices.yml` is the one file a reload leaves alone.

The gold source is the device the whole capture → build → deploy pipeline depends on: break it with
an unproven change and every future capture inherits the breakage. Encode a fix as a transform or
recipe entry, test-deploy it to a disposable device, and only then consider touching the source. This
is a sensible default for an unproven change, **not** a claim that the capture source is permanently
off-limits.

## Effect classes

| Class | Examples | Policy consequence |
|-------|----------|--------------------|
| `READ` | `getprop`, `stat`, `ls`, `df` | no approval; diagnostic log only |
| `MUTATING` | `settings put`, file push, `rm` | audited; agents need approval |
| `DESTRUCTIVE` | `rm -rf`, `pm disable-user`, `pm install`, profile deploy | audited; approval required for non-CLI actors |

Mislabelling a destructive step silently bypasses the policy layer. This is the highest-consequence declaration in the codebase.

## Dependency injection

Everything a step may touch arrives in its context. There is **no single `StepContext`** —
there are four, and `StepSpec.scope` selects which one a step receives. The split is the
enforcement mechanism for the non-negotiables, not a convenience:

```python
FleetStepContext      # scope="fleet"     artifacts, inventory, config, handle, workspace
DeviceStepContext     # scope="device"    + device, transport, state, apps
DiscoveryStepContext  # (discovery)       scanner, config, handle, workspace
TransformStepContext  # scope="transform" transforms, artifacts, config, handle, workspace
```

Read the absences — each one is load-bearing:

- `TransformStepContext` has **no transport and no device**. This is what makes "transforms
  go in `build`, never `deploy`" structural rather than a convention someone has to remember.
- `DeviceStepContext` has **no transform chain**, the same rule from the other side.
- `DiscoveryStepContext` has **no transport**: discovery decides what to open a transport
  *to*, so it cannot be handed one.
- `DeviceStepContext.device` is `Device`, never `Device | None` — a device step always has
  a target, so no step needs a `None` branch.

`transport` is already an `AuditingTransport` when it arrives. Deliberately absent from all
four: audit sink, logger, redactor. A step cannot emit audit records because it does not need
to — the transport is already wrapped and correlation ids ride a `ContextVar`.

**Composition roots** — the only places construction happens: `cli/bootstrap.py`, the HA integration's setup, `tests/conftest.py`.

## Config layering

`pack defaults` → `fleet.yml` → `group vars (by tag)` → `device vars` → `workflow with:` → `CLI flags`. Later wins. `fleetctl config show <device>` must be able to explain which layer won each key.

## Where does this code go?

| If it… | It belongs in |
|--------|---------------|
| names an Amazon package | `packs/firetv/data/` |
| works around a toybox bug | `packs/firetv/` (Fire OS quirk, not Android) |
| works around a SteamOS quirk | `packs/steamdeck/data/` (not `linux_host`, not `posix`) |
| is ADB or SSH wire behaviour | `packs/android/` or `packs/posix/` — the shared base, not a vendor pack |
| says which recipe a device needs | the pack's `app_profiles`, read at the composition root |
| parses `guisettings.xml` | `apps/kodi/` |
| retries a flaky connection | `core/transport/` as a decorator |
| decides which device a step runs on | `core/workflow/` |
| knows what "gold" means | `config/`, as policy and tags |
| is a package allow-list | `apps/kodi/data/profiles/*.yml` |

## Terms

- **Module** — anything with an interface and an implementation.
- **Seam** — where an interface lives; behaviour can be swapped without editing in place.
- **Adapter** — a concrete thing satisfying a seam.
- **Deep / shallow** — a deep module puts a lot of behaviour behind a small interface. Shallow means the interface is nearly as complex as the implementation.
- **Pack** — a registered plugin: device pack or app pack.
- **Step** — one registered unit of work with an id, params schema, required capabilities, and effect class.
- **Workflow** — an ordered set of steps with targeting, defined in YAML.
