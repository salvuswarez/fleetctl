---
description: Verify the inward-only dependency rule still holds. No arguments.
---

Verify the inward-only dependency rule still holds. No arguments.

## 1. Run the test that already enforces it

```bash
uv run pytest tests/unit/test_architecture.py -v
```

This has been part of the gate since S1. It is **AST-based, not import-based**, so it holds even for
modules that fail to import. It asserts five structural rules:

| Test | Rule |
|---|---|
| `test_core_does_not_import_packs_or_apps` | `core/` imports nothing outward |
| `test_apps_do_not_import_packs` | an app pack never knows a device pack exists |
| `test_packs_do_not_import_apps` | a device pack never knows an app exists |
| `test_a_pack_imports_no_sibling_pack_except_a_shared_base` | a pack may compose only `packs.android` or `packs.posix` |
| `test_no_shared_base_is_registered_as_a_pack` | a shared base has no entry point |

Plus `test_core_code_is_free_of_device_vocabulary`, parametrized over `kodi`, `firetv`, `fire_tv`,
`shield`, `amazon`, `xbmc`, `adb`, `toybox` — checking identifiers and *runtime* string literals.
Docstrings and comments are deliberately exempt: the rule is about coupling, not vocabulary, and the
reasons a module is shaped a certain way are worth writing down inside it.

Do not re-grep by hand for anything in that list. If the test is green, those rules hold.

## 2. If it fails

Report every violation with `file:line` from the test output. Each is an architecture bug, not a
style nit. A hit in `test_core_does_not_import_packs_or_apps` or the vocabulary test usually means a
vendor quirk leaked into the kernel — it belongs to the pack that has the quirk, **as data in
`data/*.yml`**, not as an import or a constant.

## 3. Check the two gaps the test does not cover

The test scans `core/` only, and its term list predates the SteamOS work. Both gaps are real, so
grep for them:

- **Newer device vocabulary in `src/fleetctl/core/`** — `nvidia`, `steamdeck`, `steamos`, `flatpak`,
  `com.amazon`, `pm disable-user`. None are in `FORBIDDEN_IN_CORE`.
- **`src/fleetctl/agent/` and `src/fleetctl/mcp/`** — not scanned by any architecture test. These
  compose the kernel and must reach packs only through the registry, so a pack name appearing there
  is the same bug one ring out.

Report every hit with `file:line`, and for each one name the pack it should move to. If a grep here
finds a genuine violation, say so plainly — it means the term belongs in `FORBIDDEN_IN_CORE`, or the
test needs to scan a ring it currently skips.

Use the `fleetctl-architecture` skill for what belongs in which ring.
