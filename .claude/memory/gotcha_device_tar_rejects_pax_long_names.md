---
name: gotcha_device_tar_rejects_pax_long_names
description: Python's tarfile defaults to PAX; the toybox tar on a set-top device cannot read PAX long names and aborts partway through the first member.
metadata:
  type: project
---

A Kodi profile routinely exceeds tar's 100-character name field — addon
`__pycache__` trees reach 165. Python's `tarfile` encodes that overflow as
**PAX extended headers** by default. The `tar` shipped on set-top Android
devices reads **GNU** long-name entries but not PAX.

Given a PAX archive it truncates the name mid-path and dies:

```
tar: can't remove: addons/.../baseitem_factories/__p: Is a directory
tar: bad header
```

The damage is that this is **partial and quiet**. Extraction aborts inside
the first member, so `addons/` exists with a plausible-looking subset while
`userdata/` and `media/` never appear at all. Verified on hardware
2026-08-12: an identical 133-character path extracts under GNU and fails
under PAX on the same device, same command.

**Why:** nothing in the pipeline chose a tar format, so Python's default
applied. The predecessor never hit it because a device-side `tar czf` writes
the device's own format; only a build repacked in Python is PAX.

**How to apply:** `_pack_flat` in `apps/kodi/steps.py` passes
`format=tarfile.GNU_FORMAT`, and a test asserts no member carries
`pax_headers`. Any *new* code that writes an archive destined for a device
must do the same. This is not a vendor quirk — it is every busybox/toybox
`tar`, so it belongs in the shared build path and not in a pack.

Related: [[gotcha_toybox_tar_gzip_truncation]] (the same tool, a different
bug), [[gotcha_adb_exec_cannot_see_exit_status]] — which is why the failure
reported success.
