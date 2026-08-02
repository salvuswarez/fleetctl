---
name: toybox tar -z silently truncates archives on Fire OS
description: `tar czf` on Fire OS produces a truncated gzip stream while reporting exit code 0. Split into `tar cf` then `gzip`. This is an Amazon vendor quirk, not an Android fact.
type: project
---

toybox's `tar -z` on Fire OS silently produces a **truncated gzip stream**. `tar` itself reports exit code 0, and the resulting archive is byte-identical whether pulled once or re-pulled fresh — so the corruption is baked in at creation time, not a transfer problem. Plain `tar cf` followed by a separate `gzip` pass verified clean on the same device (`tar tf` lists all entries, decompresses fully).

```sh
tar cf archive.tar -C <parent> <dir>  &&  gzip archive.tar     # create
gzip -d archive.tar.gz                &&  tar xf archive.tar   # extract
```

**Why:** Found in the predecessor project when a capture that reported success produced an archive that failed to extract on an unrelated device's deploy much later. Verifying the gzip stream after capture (decompress it fully) is what turned a silent corruption into a loud failure.

**How to apply:** This is a **Fire OS vendor quirk** and belongs in `packs/firetv`'s quirk data — not in `core/`, and not assumed for the Shield until tested there. The two-step dance costs real time on a large profile, so the Shield should be measured rather than inheriting it. Never write `tar czf` or `tar xzf` against a Fire OS device. See the `adb-device-ops` skill.
