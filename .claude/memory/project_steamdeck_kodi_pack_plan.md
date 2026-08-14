---
name: Steam Deck OLED Kodi pack — hardware-verified findings
description: SteamOS quirks read off a real Steam Deck OLED (SteamOS 3.8.24) on 2026-08-06, including the Flatpak Kodi state path that is NOT what was guessed.
type: project
---

Goal: push Kodi builds/config to a Valve Steam Deck OLED over the network.
SteamOS is a Linux box with SSH, so it composes `packs/posix` (the shared SSH
base added in S8) rather than being a new top-level category — the same way
`packs/shield` composes `packs/android`.

## Verified on hardware, 2026-08-06

Read over SSH from a real Deck (SteamOS 3.8.24, kernel 6.16.12-…-neptune).
`SshTransport` connected, authenticated, and read facts successfully.

| Fact | Value |
|---|---|
| `/etc/os-release` | `ID=steamos`, `ID_LIKE=arch`, `VARIANT_ID=steamdeck`, `VERSION_ID=3.8.24` |
| Root filesystem | **read-only** (`test -w /` → READONLY), 5.2GB partition |
| `/home` | 984GB, separate partition, writable |
| sudo | **needs a password** — `sudo -n` fails, so `use_sudo` must stay false |
| `hostname` binary | **not installed** (exit 127) — read the name with `uname -n` |
| tar / gzip | GNU tar 1.35, gzip 1.14 — `tar czf` works correctly, **no `split_gzip` quirk** |
| Kodi | installed as Flatpak `tv.kodi.Kodi`; native `~/.kodi` **absent** |

## The Flatpak state path — the guess was wrong

Expected `~/.var/app/tv.kodi.Kodi/data/.kodi`. **There is no `.kodi`
subdirectory.** Kodi's profile members sit directly in the Flatpak data dir:

```
/home/deck/.var/app/tv.kodi.Kodi/data/
├── addons/  ├── media/  ├── userdata/  ├── system/  └── temp/
```

So the state root is `/home/deck/.var/app/{identifier}/data`, with an **empty**
`app_root`. This matters because `apps/kodi` declares `STATE_SUBDIR = ".kodi"`
as a single value in `spec.py`, correct for Android and wrong here — see the
open seam question below.

## Settled: `AppStateSpec.app_roots` is per-platform

`app_root: str` became `app_roots: Mapping[str, str]` with `root_for(platform)`,
mirroring `identifiers`. Android maps to `.kodi`, linux to `""`. An absent
entry legitimately means "no subdirectory", unlike `identifier_for`, where
absence is an error. `apps/kodi` declares
`STATE_SUBDIRS = {"android": ".kodi", "linux": ""}`.

## `packs/steamdeck` — landed and exercised on hardware

Composes `packs/posix`, probes on `ID=steamos` at priority 20 (ahead of
`linux_host`'s 50), declares REACH/FACTS/EXEC/FILES/APPS/STATE/CLEANUP.
Deliberately **not** POWER: suspend/resume differs from a desktop box and no
reboot has been tested against one.

A live `kodi.capture`-equivalent ran end-to-end on 2026-08-06: probe claimed
the device, the root resolved to
`/home/deck/.var/app/tv.kodi.Kodi/data`, and `PosixStateManager.snapshot`
pulled a 1.8MB archive of 1122 entries whose top level is exactly
`addons/ media/ userdata/` — flat, matching the build contract. Kodi 21.3-Omega.

## Deploy ran successfully on hardware, 2026-08-06

`kodi.deploy` pushed `builds/build_20260807_031414.tar.gz` (342MB, built with
the `deck` profile) to the Deck through `PosixStateManager.restore`. Both
directions are now hardware-proven.

Verified on the device afterwards: 55 addons, 18 userdata entries, skin
`skin.arctic.fuse.3` present, `guisettings.xml` written, profile 471MB, free
space dropped ~482MB. **Zero `.so` files in the profile** — the prune held, and
`inputstream.*` / `pvr.*` are absent from the profile while the Flatpak still
supplies its own x86_64 copies. `system/` and `temp/` were left untouched:
they are not spec members, so restore correctly did not replace them.

Kodi was stopped via `FlatpakAppManager.stop` before the restore. The step
itself does **not** stop the app — that was done explicitly by the caller, and
is a gap worth closing if deploy is ever run from a workflow.

## The gold build carries ARM binaries — measured, not assumed

`builds/build_20260805_022600.tar.gz` (346MB, 13535 entries) was pulled from
the SMB store and inspected on 2026-08-06. It contains exactly **three**
compiled objects, and every one is **ELF ARM 32-bit**:

| Addon | Objects |
|---|---|
| `inputstream.adaptive` | 1 |
| `inputstream.rtmp` | 1 |
| `pvr.iptvsimple` | 1 |

Nothing else in the build is architecture-specific — no `script.module.*`
carries a compiled component, which had been an open worry. On the Deck all
three are supplied by the Kodi Flatpak already built for x86_64, and a
user-profile addon shadows the application image's copy, so deploying `gold`
verbatim would replace working native engines with unloadable ARM ones.

`apps/kodi/data/profiles/deck.yml` (`extends: gold`) drops the `inputstream.`
prefix and `pvr.iptvsimple`; verified that it prunes all three and differs
from gold in nothing else. `extends:` support had to be implemented in
`apps/kodi/pack.py` first — `.claude/rules/apps.md` documented it but
`_load_profile` did not have it. Lists replace rather than accumulate on
merge, which is what lets a variant *remove* an entry.

**Why:** these were guesses until they were read off the device, and one of
them was wrong in a way that would have written a Kodi profile into a
directory Kodi does not read. This is what the S2 honesty-gate rule is for.

**How to apply:** `packs/linux_host` deliberately declines a host reporting
`ID=steamos` (`DECLINED_DISTRIBUTIONS`) — its `writable_root: true` default is
false on a Deck. A `packs/steamdeck` composing `packs/posix` sets
`writable_root: false`, `use_sudo: false`, `app_data_root:
"~/.var/app/{identifier}/data"`, and `staging_dir` under `/home`, never `/`.
Resolve the `app_root` question before declaring `Capability.STATE`. See
[[architecture_rings_and_decisions]] and [[gotcha_unverified_package_lists]].
