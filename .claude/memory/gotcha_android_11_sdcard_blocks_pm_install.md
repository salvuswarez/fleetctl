---
name: gotcha_android_11_sdcard_blocks_pm_install
description: From Android 11 /sdcard is a FUSE mount system_server cannot read, so an APK staged there installs nowhere despite a successful push.
metadata:
  type: project
---

Staging an APK on `/sdcard` and running `pm install` works on Android 9 (Fire
OS 7) and fails from Android 11:

```
avc: denied { read } ... tcontext=u:object_r:fuse:s0
Error: Unable to open file: /sdcard/kodi.apk
Consider using a file under /data/local/tmp/
```

`/sdcard` is a FUSE mount and `system_server`, which performs the install, has
no SELinux permission to read it. The **push succeeds**, so every byte arrives
and only the install fails — and since
[[gotcha_adb_exec_cannot_see_exit_status]] hides the exit code, the step
reports success.

**How to apply:** `AndroidQuirks.apk_staging_dir` defaults to
`/data/local/tmp`, which is adb-writable and installer-readable on every
Android version — including the older ones, so this is a universal default and
not a per-vendor override. `AndroidAppManager.install` also re-reads the
package list afterwards and raises when the package is absent, because the
install command itself cannot be trusted to report failure.

Note `/data/local/tmp` is on the data partition, not external storage, so a
large APK consumes space `free_bytes(external_storage)` does not describe.

Verified on hardware 2026-08-12 (Android 11): Kodi 21.3, 64MB APK, staged at
`/data/local/tmp` and confirmed installed with `primaryCpuAbi=armeabi-v7a`.
