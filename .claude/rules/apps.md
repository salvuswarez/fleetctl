---
paths: ["src/fleetctl/apps/**"]
---

# App Pack Rules

An app pack manages software *on* a device and must not care which device.

1. **Never import a device pack** — declare required capabilities (`files.push`, `exec`, `state.restore`) and let the engine resolve the provider. This is what lets one Kodi build target a Fire Stick and a Shield.
2. **Transforms go in `build`, never `deploy`** — structurally enforced: `build` receives a transform chain and no transport; `deploy` receives a transport and no transform chain. If a change must differ per device, it belongs in that device's `vars`, not as a branch in deploy.
3. **A transform is pure** — directory in, list-of-changes out. No I/O, no transport, no device. That is the whole testability story for this ring.
4. **Recipes are config** — allow-lists, setting overrides, prune paths, and home-screen layouts live in `data/profiles/*.yml` with `extends:` support, not in Python dicts.
5. **Per-device state reads from `device.vars.<app>`** — never from a field on the core `Device` model. `display` and `settings` are Kodi's concerns, not the inventory's.
6. **Declare effect class on every step** — a profile deploy wipes directories; it is `DESTRUCTIVE`.
7. **Archive layout is part of the contract** — build output is flat (`addons/`, `userdata/`, `media/` at the tar root) so deploy extracts with no path rewriting.
