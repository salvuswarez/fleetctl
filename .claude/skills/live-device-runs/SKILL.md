---
name: live-device-runs
description: Drive fleetctl against real hardware from a checkout that has no config/ — probe a device, capture or deploy a profile, and inspect artifacts in the SMB store. Use when verifying a pack against a live device, reproducing a hardware-only bug, or checking what a build actually contains.
---

# Live device runs

The unit suite never touches hardware, and a fresh checkout has no `config/`,
so the CLI cannot resolve an inventory or an artifact store. This skill is how
to reach a real device anyway: construct the pieces by hand and call the
**shipped** code path, so a live run exercises what production runs.

Scripts go in `.claude/temp/` (gitignored). Anything that proves reusable
belongs back in this skill.

## The rule these runs exist to enforce

A green suite proves the code does what its fixtures say. It cannot prove the
fixtures match the device. Every hardware bug found so far was a command that
did not exist or a flag that was not accepted, silently swallowed by
`exec_ok`:

| Found | Symptom |
|---|---|
| `hostname` absent on SteamOS | exit 127, the `name` fact silently vanished |
| `flatpak info --show-version` unsupported | no output, an installed app read as absent |

So: **when a live run reports something absent, run the raw command over the
transport before touching the parser.**

## Credentials

Never in the transcript, never as a literal. Put them in the gitignored `.env`
at the repo root and resolve at the edge:

```python
from fleetctl.core.config.dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env")
password = os.environ["FLEETCTL_DECK_PASS"]
```

Check presence by **key name only** — never print a value:

```python
keys = [l.split("=", 1)[0].strip() for l in env.read_text().splitlines() if "=" in l]
print("set:", "FLEETCTL_DECK_PASS" in keys)
```

## Connecting over SSH

`SshTransport` uses `RejectPolicy`, so an unknown host key fails by design.
Verify the fingerprint against the device once, then pin it:

```bash
# on the device
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

```python
import paramiko
from fleetctl.packs.posix.transport import SshSettings, SshTransport

known = Path(os.path.expanduser("~")) / ".fleetctl" / "known_hosts"
transport = SshTransport(address, SshSettings(user="deck", password=password, known_hosts=known))
transport.connect()
```

Pin a verified key with `paramiko.HostKeys(...).add(...)` then `.save()`.

**Reading the failure mode matters** — the three states mean different things:

| Symptom | Meaning |
|---|---|
| Ping fails | Off, or off the network |
| Ping OK, port 22 **refused** | Awake, `sshd` not running |
| Ping OK, port 22 **times out** | Asleep / wifi power-save — **retry** |

`SshTransport.connect()` has no retry, so the first call after idle can fail
with nothing broken.

## Building a step context by hand

Device steps need a `DeviceStepContext`; build steps need a
`TransformStepContext` and carry no transport by design:

```python
from fleetctl.core.operations.registry import OperationRegistry
from fleetctl.core.workflow.step import TransformStepContext

handle = OperationRegistry().start("adhoc", "kodi.build", "local")
context = TransformStepContext(transforms=KodiApp("deck").transforms, artifacts=store, config={}, handle=handle, workspace=work)
result = build(context)
```

Call the real step function. Reimplementing what it does is how a live run
ends up proving something other than the shipped path.

## Reaching the SMB artifact store

```python
from fleetctl.core.artifacts.smb import SmbArtifactStore, SmbSettings

store = SmbArtifactStore(SmbSettings(
    host=os.environ["SMB_HOST"], share=os.environ["SMB_SHARE"],
    root=os.environ.get("SMB_BACKUP_DIR", "fleetctl"),
    user=os.environ["SMB_USER"], password=os.environ["SMB_PASS"],
))
store.list("builds"); store.latest("builds"); store.get(ref, local)
```

A trailing `socket aborted by peer (WSAESHUTDOWN), treating as EOF` on
teardown is normal and not a failure.

## Verifying an archive before trusting it

**Always, before any deploy or as a rollback.** A truncated archive opens
fine and fails only at the end — an interrupted build produced a 129MB file
that looked plausible next to a 342MB real one:

```python
with tarfile.open(path, "r:gz") as archive:
    for member in archive.getmembers():      # forces a full read
        if member.isfile():
            archive.extractfile(member).read()
```

`EOFError: Compressed file ended before the end-of-stream marker` means
truncated. Delete it; do not deploy it.

Check what a build actually contains — architecture comes from the ELF header,
not the filename:

```python
_MACHINES = {0x28: "ARM (32-bit)", 0xB7: "AArch64", 0x3E: "x86-64", 0x03: "x86"}
machine = struct.unpack_from("<H", blob, 18)[0] if blob[:4] == b"\x7fELF" else None
```

## Capturing as a rollback

Before anything destructive, pull the device's current state — and pass
`exclude=()`. The default capture excludes **prune the live profile** before
archiving:

```python
manager.snapshot(state_spec(exclude=()), destination)
```

Keep it outside `.claude/temp/` so a cleanup cannot eat it:
`~/.fleetctl/rollback/<device>_<date>.tar.gz`.

## Effect classes still apply

A live script is not exempt. Reads pass `Effect.READ`; anything that writes is
`MUTATING`; anything that replaces or deletes is `DESTRUCTIVE`. A read-only
probe whose commands are unlabelled is indistinguishable from a change in the
audit trail.

## Related

- `.claude/skills/adb-device-ops/SKILL.md` — the same territory for ADB.
- `.claude/skills/pack-authoring/SKILL.md` — where findings become pack data.
- Project memory: `gotcha_steamos_ships_no_hostname_binary`,
  `gotcha_flatpak_show_version_unsupported`,
  `gotcha_steam_deck_wifi_powersave_drops_tcp`,
  `project_steamdeck_kodi_pack_plan`.
