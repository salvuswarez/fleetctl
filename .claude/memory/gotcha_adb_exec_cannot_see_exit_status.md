---
name: gotcha_adb_exec_cannot_see_exit_status
description: AdbTransport.exec returns shell stdout and never inspects the exit status, so any command that runs and fails reads as success.
metadata:
  type: project
---

`AdbTransport.exec` calls `adb_shell`'s `shell()` and returns its output. It
raises only when the **call** throws — a dropped connection or a timeout. It
never sees the command's exit status, because `shell()` does not return one.

So a command that runs and fails is indistinguishable from success. Observed
on hardware 2026-08-12: `pm install` printed a Java stack trace and exited
**255**, and `kodi.install_base` reported "Kodi 21.3 installed" for a device
with no Kodi on it.

This is very likely the real mechanism behind
[[gotcha_pm_disable_by_fireos_version]]. `verify_disable_user` reads as a Fire
OS vendor quirk, but re-reading state is the only way *any* Android device can
confirm *any* command — Fire OS was simply where it first bit.

**A second trap sits on top of it.** The obvious verification —
`exec_ok("ls <path>")` and test for empty output — does not work either:
stderr is merged into stdout, so a missing directory answers `ls: ... No such
file or directory`, which is **non-empty** and reads as proof the directory
exists. `AndroidStateManager._verify` had exactly this bug and passed a
restore in which two of three members were absent.

**How to apply:** never treat a command returning without raising as evidence
it worked. After any destructive Android operation, re-read state and parse
something unambiguous — `ls -1 <path> 2>/dev/null | wc -l` and require a
non-zero count, or `... && echo OK` and require the sentinel. Never
substring-match a path against output that might be an error message
mentioning that path.

Fixing `exec` to append `; echo __EXIT__$?` and parse it would remove the root
cause and let several per-vendor `verify_*` quirks retire. Not attempted — it
changes every Android call path at once.
