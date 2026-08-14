---
name: firestick_manager was the predecessor and behavioural source of truth
description: Retired 2026-08-06 (S7 cutover). Where fleetctl's ported behaviour came from, what was worth copying, and what was stale documentation debt left behind on purpose.
type: reference
---

**Retired 2026-08-06.** `firestick_manager` no longer runs — the S7 cutover landed and the repo was
archived (moved out of `dev/salvuswarez/`, not force-deleted, since it held gitignored real device
data — captured Kodi backups, real MAC/IP inventory — that git history alone wouldn't have preserved).
It was the source of truth for **behaviour verified against real hardware**, not for architecture, and
that behaviour now lives here, ported.

**Worth porting** (each has its own memory entry or lives in the `adb-device-ops` skill): netcat upload and its three constraints; `tar cf` + separate `gzip`; flat build archives with no `.kodi/` wrapper; single-archive transfer rather than per-file sync; size-scaled timeouts; the operation registry's working cancellation, debounced flush and restart handling; MAC → serial → IP reconciliation that only overwrites on a real value.

**Not worth porting:** its `.claude/skills/adb-device-ops` documents the `adb` binary and a `core.py`/`Firestick` architecture that no longer exists in that repo — stale documentation debt. Its `const.py` mixes ADB paths, Kodi prune lists, Fire OS bloat and SMB defaults in one module. Its `Device` model carries Kodi's `display` and `settings` as core inventory fields. Its `FleetService` is eight near-identical `start_*` methods over a closed `OperationType` enum.

Known live gaps in that repo at the time `fleetctl` started, worth backporting there since it runs for months yet: the CLI never calls `logging.basicConfig`, so every `debug`/`info` call is discarded; `SmbConfig` is a dataclass with a plaintext `smb_pass` and no `repr=False`, so its generated `__repr__` would print the credential; two bare `except: pass` in `service.py`.

**How to apply:** The repo is gone from `dev/salvuswarez/`; don't cite its paths, skills, or agents as
live anymore. If a behaviour question comes up that isn't covered by an existing memory entry here,
it wasn't ported — treat it as a gap to reimplement and verify against real hardware, not as code to
go dig up from the archive.
