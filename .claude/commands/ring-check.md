Verify the inward-only dependency rule still holds. No arguments.

1. Grep `src/fleetctl/core/` for imports of `packs`, `apps`, or any device/app vocabulary (`kodi`, `firetv`, `shield`, `amazon`, `xbmc`, `.kodi`).
2. Grep `src/fleetctl/apps/` for imports of `fleetctl.packs`.
3. Grep `src/fleetctl/packs/` for imports of `fleetctl.apps`.
4. Report every hit with `file:line`. Each is an architecture bug, not a style nit.

Use the `fleetctl-architecture` skill for what belongs in which ring. A hit in step 1 usually means a vendor quirk leaked into the kernel — it belongs to the pack that has the quirk, as data.
