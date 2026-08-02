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
| `packs/` | what a device *is* | `core/` | `android` (shared base), `firetv`, `shield`, `linux_host`, `generic_net` |
| `apps/` | software *on* a device | `core/` | `kodi` |

**Dependencies point inward only.** `apps/` never imports `packs/` — it declares capabilities and the engine resolves the provider. That indirection is the entire reason one Kodi build can target both a Fire Stick and a Shield.

## The seams

| Seam | Protocol | Adapters |
|------|----------|----------|
| Talk to a device | `Transport` (= `Reachable` + `CommandRunner` + `FileTransfer`) | `AdbTransport`, `SshTransport`, `LocalTransport`, `NullTransport`, `FakeTransport`, `AuditingTransport` (decorator) |
| Store artifacts | `ArtifactStore` | `SmbArtifactStore`, `LocalArtifactStore` |
| Identify a host | `DeviceProbe` | one per device pack, ordered; `generic_net` claims last |
| Shape a profile | `ProfileTransform` | one per Kodi transform; pure |
| Record effects | `AuditSink` | `JsonlAuditSink`, `InMemoryAuditSink` |
| Resolve a secret | `SecretProvider` | `HaConfigEntryProvider`, `EnvProvider`, `KeyringProvider` |
| Persist op records | `OperationSink` | Smb, Null |

**Rule:** a seam ships with two adapters or it is hypothetical. The second is usually the test double.

## The verb vocabulary

`reach` · `facts` · `exec` · `files` · `apps` · `settings` · `power` · `state` · `cleanup`

A pack declares which it supports; a step declares which it requires; the engine checks at **plan time**, before touching anything.

## Effect classes

| Class | Examples | Policy consequence |
|-------|----------|--------------------|
| `READ` | `getprop`, `stat`, `ls`, `df` | no approval; diagnostic log only |
| `MUTATING` | `settings put`, file push, `rm` | audited; agents need approval |
| `DESTRUCTIVE` | `rm -rf`, `pm disable-user`, `pm install`, profile deploy | audited; approval required for non-CLI actors |

Mislabelling a destructive step silently bypasses the policy layer. This is the highest-consequence declaration in the codebase.

## Dependency injection

Everything a step may touch arrives in `StepContext`:

```python
@dataclass(frozen=True, slots=True)
class StepContext:
    device: Device | None
    transport: Transport          # already an AuditingTransport
    artifacts: ArtifactStore
    inventory: DeviceStore
    config: Mapping[str, Any]     # already layer-resolved
    handle: OperationHandle
    workspace: Path
```

Deliberately absent: audit sink, logger, redactor. A step cannot emit audit records because it does not need to — the transport is already wrapped and correlation ids ride a `ContextVar`.

**Composition roots** — the only places construction happens: `cli/bootstrap.py`, the HA integration's setup, `tests/conftest.py`.

## Config layering

`pack defaults` → `fleet.yml` → `group vars (by tag)` → `device vars` → `workflow with:` → `CLI flags`. Later wins. `fleetctl config show <device>` must be able to explain which layer won each key.

## Where does this code go?

| If it… | It belongs in |
|--------|---------------|
| names an Amazon package | `packs/firetv/data/` |
| works around a toybox bug | `packs/firetv/` (Fire OS quirk, not Android) |
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
