---
name: firestick_manager is the predecessor and behavioural source of truth
description: Where fleetctl's ported behaviour comes from, what is worth copying, and what is stale documentation debt that should not be copied.
type: reference
---

`C:\Users\chugh\Documents\dev\firestick_manager` — the predecessor. Still running and still serving the Home Assistant integration until the S7 cutover. It is the source of truth for **behaviour verified against real hardware**, not for architecture.

**Worth porting** (each has its own memory entry or lives in the `adb-device-ops` skill): netcat upload and its three constraints; `tar cf` + separate `gzip`; flat build archives with no `.kodi/` wrapper; single-archive transfer rather than per-file sync; size-scaled timeouts; the operation registry's working cancellation, debounced flush and restart handling; MAC → serial → IP reconciliation that only overwrites on a real value.

**Not worth porting:** its `.claude/skills/adb-device-ops` documents the `adb` binary and a `core.py`/`Firestick` architecture that no longer exists in that repo — stale documentation debt. Its `const.py` mixes ADB paths, Kodi prune lists, Fire OS bloat and SMB defaults in one module. Its `Device` model carries Kodi's `display` and `settings` as core inventory fields. Its `FleetService` is eight near-identical `start_*` methods over a closed `OperationType` enum.

Known live gaps in that repo at the time `fleetctl` started, worth backporting there since it runs for months yet: the CLI never calls `logging.basicConfig`, so every `debug`/`info` call is discarded; `SmbConfig` is a dataclass with a plaintext `smb_pass` and no `repr=False`, so its generated `__repr__` would print the credential; two bare `except: pass` in `service.py`.

**How to apply:** When porting a behaviour, read the predecessor's implementation *and* its surrounding comments — the comments carry the incident history that explains why the code looks odd. Do not port its module structure. Do not cite its skills or agents as current.
