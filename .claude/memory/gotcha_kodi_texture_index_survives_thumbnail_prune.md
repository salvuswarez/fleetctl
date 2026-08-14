---
name: Pruning Thumbnails without Textures13.db leaves a dangling index, a contributing OOM cause
description: A capture/build that strips userdata/Thumbnails but leaves userdata/Database/Textures13.db intact deploys a device with an index full of references to files that no longer exist — it re-fetches them all at startup instead of lazily, adding real memory churn on a low-RAM stick.
type: gotcha
---

Verified on real hardware (predecessor repo, 2026-07-30): a freshly-deployed 1.7GB-RAM Fire Stick
logged 87 `"DoWork - Direct texture file loading failed"` entries concentrated at startup, each
triggering a background re-cache instead of a lazy on-demand fetch. Root cause: the prune step
removed the cached thumbnail files (`userdata/Thumbnails`) but not the SQLite index that lists them
(`userdata/Database/Textures13.db`, plus its `-wal`/`-shm` siblings) — so the deployed device started
with a database confidently pointing at thumbnails that don't exist.

**This was one of three compounding causes of a real low-memory kill**, not the sole cause — a dead
MariaDB backend (see the shared-backend reference memory) and Amazon bloat apps stuck in DNS-blocked
retry loops both added independent memory pressure at the same time. `logcat` showing several
*unrelated* processes die within the same ~300ms window is the signature of system-wide memory
pressure (Android's low-memory killer), not an app-specific bug — worth checking before assuming a
Kodi/skin config regression.

**Why it matters here:** any prune/reset step that clears cached content must also clear the index
that tracks it, or the two go out of sync in a way that only shows up as startup churn on the
device — not as a build-time or deploy-time error.

**How to apply:** if `apps/kodi`'s prune/profile-transform path ever touches `userdata/Thumbnails`
(or any other cached-content directory with its own SQLite index), prune the matching index file(s)
in the same step. If a deployed device is reported unstable, don't assume the Kodi/skin config is
misconfigured — diff the transferred config against the gold source first, then check `logcat` for a
multi-process death cluster before concluding it's an app-level bug.
