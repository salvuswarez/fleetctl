---
name: adb-device-ops
description: ADB behaviour against real Android TV hardware — connection lifecycle, upload over netcat, shell quirks, and Fire OS-specific traps. Use when implementing or debugging AdbTransport, or any pack that talks to an Android device.
---

# ADB Device Operations

`fleetctl` uses **pure-Python ADB** (`adb-shell`), not the `adb` binary — no external tool on PATH, and it works identically inside a Home Assistant container. All of this lands behind `AdbTransport` (S1/S2); nothing above the transport seam should know any of it.

## A command that fails is indistinguishable from one that worked

Read this first. Every other trap on this page is a symptom of it.

`AdbTransport.exec` (`packs/android/transport.py`) calls `adb_shell`'s `shell()` and returns its output. It raises only when the **call** throws — a dropped connection, a timeout. It never sees the command's exit status, because `shell()` does not return one.

Observed on hardware: `pm install` printed a Java stack trace and exited **255**, and `kodi.install_base` reported "Kodi 21.3 installed" for a device with no Kodi on it.

**The obvious verification does not work either.** stderr is merged into stdout, so `exec_ok("ls <path>")` tested for empty output answers `ls: ... No such file or directory` — non-empty, and therefore read as proof the directory exists. `AndroidStateManager._verify` had exactly that bug and passed a restore in which two of three members were absent.

So, after any operation that matters:

```sh
ls -1 <path> 2>/dev/null | wc -l      # require a non-zero count
<command> && echo FLEETCTL_OK          # require the sentinel
```

Never substring-match a path against output that might be an error message *containing* that path. Never treat "returned without raising" as evidence of anything.

Fixing `exec` to append `; echo __EXIT__$?` and parse it would remove the root cause and let several per-vendor `verify_*` quirks retire. It is **not attempted** — it changes every Android call path at once.

## Connection lifecycle

| Fact | Consequence |
|------|-------------|
| Port is always **5555** | ADB-over-network default; no pairing flow exists in this codebase |
| Handshake is expensive | Hold **one connection per operation**, not per command. The predecessor paid ~35 handshakes for a 35-command maintenance run before this was fixed. |
| RSA signer load is expensive | Cache it once per process, not per connection |
| Device must already be authorized | An unauthorized device hangs at auth until timeout rather than erroring cleanly |
| Key identity matters | The CLI and the HA integration hold **separate** key pairs. Authorizing one does not authorize the other. |

Timeouts do **not** inherit from the connection. `adb_shell`'s `shell()`/`pull()` each take their own `transport_timeout_s`/`read_timeout_s` and fall back to a 10s library default if unset — far too short for a `tar` over a large directory or a multi-hundred-MB transfer.

Scale timeouts with data size. A flat timeout is how the predecessor silently truncated archives.

## Uploads go over netcat, not `push()`

**`adb_shell`'s `push()` does not work against these devices.** Measured against a real Fire TV: it moved *zero* bytes and hung until timeout for anything beyond a few MB — the destination file was never created — from both a workstation and Home Assistant. Netcat moves the same payload at 5–12 MB/s.

`shell()` and `pull()` are unaffected and work fine. Do not "unify" pull onto netcat.

Three constraints, all found the hard way:

1. **The listener cannot be backgrounded.** `adb_shell` closes the shell stream when a command returns, and the device tears down the process group with it — killing a `&`-backgrounded `nc` before anything connects. `nohup` and `setsid` do not save it. Hold `toybox nc -l` running on its **own ADB connection in a worker thread**; it exits naturally when the transfer socket closes.
2. **`nc` drops its buffered tail** if the sender closes as soon as the last byte is written — transfers arrived 8–24 KB short. Wait for the device-side file to reach the expected size *before* closing.
3. **Always md5-check the result.** This is the only thing standing between a short write and a corrupt deploy. Never remove it.

Do not probe the port before connecting: `nc -l` accepts exactly one connection, so a probe consumes the listener the transfer needs.

## Archives: never `tar czf`

toybox's `tar -z` on Fire OS **silently produces a truncated gzip stream**. `tar` reports exit code 0, and the archive is byte-identical on re-pull, so the corruption is baked in at creation — it is not a transfer problem.

```sh
# create
tar cf archive.tar -C <parent> <dir>    &&  gzip archive.tar
# extract
gzip -d archive.tar.gz                  &&  tar xf archive.tar -C <dest>
```

This is a **Fire OS vendor quirk**, not an Android fact — it belongs to `packs/firetv`, and the Shield must not inherit it untested.

### Write GNU tar, never PAX

A Kodi profile routinely exceeds tar's 100-character name field — addon `__pycache__` trees reach 165. Python's `tarfile` encodes that overflow as **PAX extended headers** by default, and the `tar` on a set-top Android device reads **GNU** long names but not PAX. Given a PAX archive it truncates the name mid-path and dies:

```
tar: can't remove: addons/.../baseitem_factories/__p: Is a directory
tar: bad header
```

The damage is partial and quiet: extraction aborts inside the first member, so `addons/` exists with a plausible-looking subset while `userdata/` and `media/` never appear. An identical 133-character path extracts under GNU and fails under PAX on the same device, same command.

`_pack_flat` in `apps/kodi/steps.py` passes `format=tarfile.GNU_FORMAT`, and a test asserts no member carries `pax_headers`. Any new code writing an archive destined for a device must do the same. Unlike `tar -z` truncation this is **not** a vendor quirk — it is every busybox/toybox `tar` — so it belongs in the shared build path, not in a pack.

## Package management

```sh
pm disable-user --user 0 <package>   # reversible; preferred over uninstall
pm list packages -d                  # verify what actually got disabled
pm trim-caches 16G
pm install -r <apk>
```

**`pm disable-user` silently no-ops on old Fire OS.** On Fire OS 5.x (1st-gen stick hardware) it is blocked for many system packages from a non-root shell and fails without a useful error. It works on Fire OS 7.x. Always verify with `pm list packages -d` rather than assuming success — and never report a debloat as successful without that check. (Re-reading state is how *any* Android device confirms *any* command; Fire OS is just where it first bit.)

**Stage APKs in `/data/local/tmp`, never `/sdcard`.** From Android 11 `/sdcard` is a FUSE mount that `system_server` — which performs the install — has no SELinux permission to read:

```
avc: denied { read } ... tcontext=u:object_r:fuse:s0
Error: Unable to open file: /sdcard/kodi.apk
Consider using a file under /data/local/tmp/
```

The push succeeds, so every byte arrives and only the install fails. `AndroidQuirks.apk_staging_dir` defaults to `/data/local/tmp`, which is adb-writable and installer-readable on **every** Android version — a universal default, not a per-vendor override. `AndroidAppManager.install` re-reads the package list afterwards and raises when the package is absent, because the install command cannot be trusted to report failure.

Note `/data/local/tmp` is on the data partition, so a large APK consumes space `free_bytes(external_storage)` does not describe.

## Power state: a sleeping box stays on the network

After `KEYCODE_SLEEP`, ping, TCP/5555 and ADB all keep answering while `mWakefulness` reads `Asleep`. A ping-based or `device_tracker`-based trigger therefore **never transitions**, and an automation built on one looks correct and silently never fires. Read `mWakefulness` explicitly — `Toolkit.device_power` parses `dumpsys power | grep mWakefulness=` in `packs/android/actions.py`.

**There are four wakefulness states, not two.** `Dreaming` means the screensaver is up: the device is on and may already be playing something. An automation firing on every `off → on` also fires when a screensaver exits, yanking the foreground away from whatever was playing. Condition on the specific transition (`from_state.attributes.power_state == 'asleep'`), never on truthiness.

This is the **opposite** failure from a Steam Deck, where wifi power-save drops TCP while ICMP keeps answering. Two platforms, two inferences — which is exactly why neither should be guessed.

## What ADB cannot do

Both of these report success and change nothing — instances of the exit-status problem above.

**A launcher can be installed but not selected.** `cmd package set-home-activity` prints `Success` and leaves HOME unchanged; `cmd role add-role-holder ... android.app.role.HOME` errors on nothing and changes nothing, with or without `--user 0`. This is Android behaving correctly — silently reassigning HOME from a debug shell is launcher-hijack, so the role system requires on-device consent, and vendor firmware pins it further. `cmd role` has no `get-role-holders` on these builds, so the role cannot even be read back: press HOME and check `dumpsys activity activities | grep mResumedActivity`. If you ever clear the HOME role, re-add a known-good launcher **in the same command chain** — a dropped connection between clear and add leaves the device at `FallbackHome`. A launcher's own prefs live in `/data/data/<pkg>/shared_prefs/`, `Permission denied` for uid 2000, so in-launcher settings are not configurable either.

**Kodi cannot be made to start at boot.** Its only exported activity is `org.xbmc.kodi/.Splash` with `DEFAULT` and `BROWSABLE` and **no `HOME` category**; only `com.google.android.tvlauncher` and `com.android.tv.settings` answer a HOME intent query; and `secure boot_to_app`, `global boot_to_app` and `secure default_home` all return `null` — the platform exposes no such key. Third-party autostart APKs are a dead category by platform design (Android 10 restricts background activity starts, and TV builds are stricter still). Do not promise autostart as a fleetctl feature.

ADB itself is **not** subject to that restriction, which is why `kodi.launch` works — `am start` from an adb shell is not a background app start. The supported path is an external trigger calling `kodi.launch`, which resolves the activity generically (`cmd package resolve-activity --brief`, leanback category first) and then verifies with `pidof`, because `am start` reports failure on stdout where the command layer cannot see it.

## Discovery

```sh
getprop ro.product.model            # empty => treat as "not a device I recognize"
getprop ro.product.manufacturer     # vendor discrimination
getprop ro.serialno
getprop ro.build.version.release
settings get global device_name     # friendly name; may literally return "null"
```

Ping-sweep notes: send **2 packets, not 1** — a single dropped ICMP packet on weaker/older WiFi radios silently drops a live host before it ever reaches the ADB probe. Retry the ADB probe once with a short backoff for the same reason.

## Traps

| Symptom | Cause | Fix |
|---------|-------|-----|
| Push moves 0 bytes, hangs | `adb_shell push()` | use the netcat path |
| Transfer lands 8-24 KB short | closed before `nc` flushed | wait for remote size, then close |
| Archive extracts partially | `tar czf` / `tar xzf` | split `tar` and `gzip` |
| Debloat "succeeds", nothing disabled | Fire OS 5.x restriction | verify with `pm list packages -d` |
| Whole scan dies on one host | connect exception escaped the probe | catch it; return `None` |
| Auth times out on a known-good device | wrong key identity | check which key store the consumer uses |
| Command truncated on a big directory | default 10s timeout | pass an explicit, size-scaled timeout |
| Deploy fails mid-extract, no space | no pre-flight check | check free space for archive + extracted + headroom |
| Step reports success, nothing changed | exit status invisible | re-read state; require a count or a sentinel |
| `addons/` partly extracted, `userdata/` absent | PAX archive from Python `tarfile` | `format=tarfile.GNU_FORMAT` |
| Push succeeds, install does nothing | APK staged on `/sdcard` (FUSE) | stage in `/data/local/tmp` |
| Wake automation never fires | box answers the network while asleep | read `mWakefulness`, not reachability |
| Launcher installed but never active | HOME role needs on-device consent | not automatable; verify with `mResumedActivity` |

One open case, **not root-caused**: a Fire TV stick stopped answering ADB immediately after a successful deploy — ping fine, 5555 open, only the handshake timing out — while a sibling stick on the same key answered instantly, which rules out the key store. The deploy itself landed and runs correctly; access did not recover in that session. It matters because `kodi-deploy-all` and `kodi-refresh` both run `kodi.apply_device_config` right after `kodi.deploy` against the same device. If a device shows this exact signature, check whether it has re-authorized before running anything else against it, and treat a second prompt reappearing as its own investigation rather than something already understood.

## Never

- Interpolate an unvalidated value into a device shell command. Validate the path, the id, and the value — `shlex.quote` is necessary, not sufficient.
- Treat "no output" as success. A dropped connection and a command that legitimately printed nothing must be distinguishable.
- Log full commands at DEBUG without redaction — device settings can carry credential-bearing URLs.
