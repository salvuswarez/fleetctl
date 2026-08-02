---
name: adb_shell push() moves zero bytes; uploads go over netcat
description: Against real Fire TV hardware adb_shell's push() transfers nothing for payloads over a few MB. Uploads must stream to `toybox nc` on the device instead. pull() and shell() are unaffected.
type: project
---

Measured 2026-08-01 against a real Fire TV, from both a dev workstation and Home Assistant: `adb_shell`'s `push()` moved **zero bytes** and hung until timeout for anything beyond a few MB — the destination file was never even created. The same host sustained 5–12 MB/s streaming into `toybox nc` on the device. `shell()` and `pull()` are unaffected and work correctly; do not "unify" pull onto netcat.

Three constraints, all found the hard way:

1. **The listener cannot be backgrounded.** `adb_shell` closes the shell stream when a command returns and the device tears the process group down with it, killing a `&`-backgrounded `nc` before anything connects. `nohup` and `setsid` do not help. Hold `nc -l` running on its own ADB connection in a worker thread; it exits naturally when the transfer socket closes.
2. **`nc` drops its buffered tail** if the sender closes as soon as the last byte is written — transfers arrived 8–24 KB short. Wait for the device-side file to reach the expected size before closing.
3. **Always md5-check the result.** It is the only thing standing between a short write and a corrupt deploy.

Do not probe the port before connecting — `nc -l` accepts exactly one connection, so a probe consumes the listener the transfer needs.

**Why:** Verified on real hardware in the predecessor project after a deploy failed mid-`userdata` with no useful error. This is Android/adb_shell behaviour, not Fire OS specific, so it belongs in `AdbTransport` rather than a vendor pack.

**How to apply:** Encode all three constraints in `AdbTransport.put()` at S1/S2. Never remove the digest check. See the `adb-device-ops` skill and [[reference_predecessor_firestick_manager]].
