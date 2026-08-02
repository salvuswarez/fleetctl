---
name: adb-device-ops
description: ADB behaviour against real Android TV hardware — connection lifecycle, upload over netcat, shell quirks, and Fire OS-specific traps. Use when implementing or debugging AdbTransport, or any pack that talks to an Android device.
---

# ADB Device Operations

`fleetctl` uses **pure-Python ADB** (`adb-shell`), not the `adb` binary — no external tool on PATH, and it works identically inside a Home Assistant container. All of this lands behind `AdbTransport` (S1/S2); nothing above the transport seam should know any of it.

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

## Package management

```sh
pm disable-user --user 0 <package>   # reversible; preferred over uninstall
pm list packages -d                  # verify what actually got disabled
pm trim-caches 16G
pm install -r <apk>
```

**`pm disable-user` silently no-ops on old Fire OS.** On Fire OS 5.x (1st-gen stick hardware) it is blocked for many system packages from a non-root shell and fails without a useful error. It works on Fire OS 7.x. Always verify with `pm list packages -d` rather than assuming success — and never report a debloat as successful without that check.

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

## Never

- Interpolate an unvalidated value into a device shell command. Validate the path, the id, and the value — `shlex.quote` is necessary, not sufficient.
- Treat "no output" as success. A dropped connection and a command that legitimately printed nothing must be distinguishable.
- Log full commands at DEBUG without redaction — device settings can carry credential-bearing URLs.
