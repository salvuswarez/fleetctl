---
paths: ["src/fleetctl/core/**"]
---

# Core Kernel Rules

`core/` is the innermost ring. It knows nothing about Fire TV, Shields, PCs, or Kodi.

1. **No device-specific or app-specific knowledge** — no package names, no vendor quirks, no `.kodi` paths. If a workaround exists for one vendor's bug, it belongs in that pack as data.
2. **No imports from `packs/` or `apps/`** — dependencies point inward only. A violation here is an architecture bug, not a style nit.
3. **Seams are `Protocol`s, not ABCs** — structural typing, no inheritance required to satisfy one.
4. **A seam ships with two adapters or it isn't a seam** — one adapter is hypothetical. The second is usually the test double (`FakeTransport`, `LocalArtifactStore`, `InMemoryAuditSink`).
5. **Segregate interfaces** — `Reachable` / `CommandRunner` / `FileTransfer` compose into `Transport`. A probe depends on `CommandRunner`, not on all of it.
6. **Construct nothing** — dependencies arrive via `StepContext` or a constructor. No module-level singletons, no `AdbTransport(...)` inside a step.
7. **Cross-cutting concerns are decorators** — auditing, retry, and rate-limiting wrap a `Transport`; they are never inlined into callers.
8. **Pure where it can be pure** — planning, config layering, reconciliation and redaction take data and return data. Keep I/O at the edges.
9. **Every exception derives from `FleetError`** — with domain context as instance attributes and `raise ... from exc` chaining.
10. **Secrets are `SecretStr`** and never appear in a `repr`, a log, or an audit record.
11. **No single stored network field is a device identity.** A MAC identifies an *interface* and an address identifies a *lease*. When a MAC and a serial disagree, **the serial wins** — a box with both ethernet and wifi reports whichever interface answered, so a scan over each describes one device twice. Two devices with differing MACs and *no* serial stay separate: a reused DHCP lease is the ordinary explanation and there is no evidence there. `reconcile` must also collapse the stored fleet before *and* after merging discovery, or a duplicate is unremovable — matching finds only the first record, updates it, and writes both back, so a manual deletion is undone by the next sweep.
