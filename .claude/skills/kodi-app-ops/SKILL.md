---
name: kodi-app-ops
description: Kodi behaviour verified against real hardware — settings that write correctly and never take effect, what a gold build carries that it should not, caches a deploy does not invalidate, and what can and cannot be delivered into a profile. Use when working in apps/kodi, changing a profile recipe or transform, or debugging a deploy that reported success and changed nothing.
---

# Kodi App Operations

Everything here was observed on a device. The unifying symptom is **the step said it worked and
nothing changed** — Kodi is unusually good at accepting a change and ignoring it.

A Kodi deploy is not verified done when the transfer step reports success. It is verified when the
on-device result is re-read and shown to reflect the new state.

## Settings that write correctly and do nothing

### `default="true"` discards the value

`default="true"` asserts the value equals the addon's (or Kodi's) default, and Kodi is free to discard
a setting marked that way on load. Writing a non-default value without clearing the attribute leaves
a file that greps back exactly as intended and has no effect:

```xml
<setting id="downloads" default="true">true</setting>   <!-- ignored -->
<setting id="downloads">true</setting>                  <!-- applied -->
```

**There are two independent writers and both had to be fixed** — which is the whole reason this bug
reappeared after being fixed once:

| Writer | Where | Role |
|---|---|---|
| `_apply_file` | `apps/kodi/device_config.py` | per-device reapply |
| `ApplySettings` | `apps/kodi/transforms/settings.py` | build-time transform |

Both now `attrib.pop("default", None)` whenever they change a value, and a test asserts the attribute
is gone. Settings already non-default carry no attribute, which is why per-device `videoplayer.*`
overrides worked while the first attempt at Umbrella's `downloads` did not.

The transforms only rewrite a file when a value actually changes, so **re-running will not repair an
already-correct-looking value** — reset the setting first, then apply. If a third settings writer is
ever added, this is the first thing to check.

### Kodi 21 moved the cache out of `advancedsettings.xml`

Kodi 21 Omega moved caching into GUI settings. The `<cache>` block is still parsed without complaint
and **does nothing**. Measured on Kodi 21.3:

| Where | Value | Effect |
|---|---|---|
| `advancedsettings.xml` `<cache><memorysize>` | 150MB | **inert** |
| `guisettings.xml` `filecache.memorysize` | 32MB | live |

A profile carrying careful cache tuning was actually running a 32MB cache. Tune through
`apply_settings` on `guisettings.xml` (`shield.yml` sets `filecache.memorysize` to 200). The same
applies to `filecache.buffermode`, `filecache.readfactor`, `filecache.chunksize`. Kodi reserves
roughly **3x** `memorysize` in RAM, so budget against measured free memory, not total.

Do not add a `<cache>` block to `advancedsettings.xml`, and do not trust one you find there — check
the Kodi version first. That file is still load-bearing: on this fleet it holds the MySQL
`<videodatabase>` block, so it must be **merged into, never replaced**.

### A stripped setting must be creatable on reapply

`StripDeviceSettings` removes hardware-specific settings from a build and `kodi.apply_device_config`
puts each device's own values back. The two only compose if reapply can **create** a setting that is
not in the file — the settings a device most needs to override are precisely the ones the strip
removed. `_apply_file` originally skipped an absent setting, silently reducing per-device display
calibration to a no-op. It now creates the element.

**Still open:** `apply_overscan` (`apps/kodi/device_config.py`) has **no production caller**. It is
defined and unit-tested and nothing invokes it, so `overscan` in `vars.kodi.display` is recorded by
`kodi.read_display`, accepted by `validate_display`, and never applied — the config key promises
behaviour that never runs. Overscan also lives inside the `<resolutions>` calibration blocks, which
the strip removes and only Kodi regenerates, so applying it needs Kodi to have launched at least once
after a deploy.

When adding anything that removes content from a build, check what is supposed to put it back and
confirm that path can handle absence.

## A gold build carries the capture device's hardware

`kodi.build` produces one artifact for the whole fleet, but the `userdata/guisettings.xml` inside it
comes verbatim from **one device's** capture:

| Setting | What a Fire Stick capture contributes |
|---|---|
| `videoscreen.resolution` | a *mode index*, meaningless on other hardware |
| `<resolutions>` calibration | 21 blocks, every one with `<refreshrate>0.000000</refreshrate>` |
| `audiooutput.audiodevice` / `passthroughdevice` | Android AudioTrack device strings |
| `audiooutput.passthrough` | `true`, explicitly set |

Across identical sticks this is invisible. Deployed to a Steam Deck it produced zero calibration
entries matching the real panel, and Kodi died with **SIGFPE** seconds into a 4K HEVC 23.976fps
stream. Kodi self-heals *some* of it — `ValidateOutputDevices` rewrites the audio device strings at
startup — but not `videoscreen.resolution`, the calibration blocks, or `audiooutput.passthrough`.

`StripDeviceSettings` (`apps/kodi/transforms/device_settings.py`) now runs in **every** build, between
`prune_addons` and `apply_settings`, driven by `strip_device_settings` in the recipe. It is
unconditional — no recipe can opt out by omission — because `apply_device_config` only *overlays*
`device.vars.kodi` and returns early for a device with no vars. Overlaying is not neutralising, so a
newly-added device used to inherit the capture source's hardware silently.

Side effect worth knowing: a device with no `vars.kodi.display` now gets Kodi's own detection rather
than the gold stick's overscan. Correct, but a behaviour change for any Fire Stick that relied on the
inheritance.

The SIGFPE's faulting instruction was never confirmed — `coredumpctl` reported the corefile
inaccessible and Kodi's crashlog says gdb is not installed. Zero refresh rate in the matched
calibration entry is strong circumstantial evidence, not proof. The fix removes the class regardless.

## A build must match the device it lands on

`registry.discover()` loads packs with `entry.load()()` — **no arguments** — so the one registered
`KodiApp` is always `KodiApp(profile="gold")` and its `profile` parameter is reachable only by code
that builds its own instance. Nothing in the HA path does, so a Steam Deck capture built through the
panel produced a **gold** image: ARM binaries the Deck cannot execute, plus the display settings
behind the SIGFPE. It looked like it worked.

Profile resolution therefore lives where the knowledge is:

- The **device pack** declares `app_profiles` (`{"kodi": "deck"}`) — hardware is the reason, so the
  pack that knows the hardware states it.
- The **composition root** (`cli/main.py:_transforms_for`) resolves it, because the decision needs the
  artifact store, the inventory and the pack, and no single ring holds all three. Order: explicit
  flag, then `device.vars.kodi.profile`, then the pack default.
- The **app pack** gains `transforms_for(name)` and stays device-agnostic.

The resolved name is written onto the build's metadata, and `deploy` uses it twice: it refuses a build
shaped for other hardware, and when no build is named it picks the newest one **matching this
device's profile** rather than the newest overall. Both matter because `kodi-refresh` deploys to a
mixed fleet without naming a build — publishing one Deck build made it the newest, and every Fire
Stick would have received it.

## Caches the deploy path does not invalidate

Two instances of one shape: content is replaced, an index that describes it is not.

- **`Textures13.db` survives a thumbnail prune.** Pruning `userdata/Thumbnails` without
  `userdata/Database/Textures13.db` (and its `-wal`/`-shm` siblings) leaves a database confidently
  pointing at files that no longer exist. A freshly-deployed 1.7GB-RAM Fire Stick logged 87
  `"DoWork - Direct texture file loading failed"` entries at startup, each triggering a background
  re-cache. `CAPTURE_EXCLUDE` in `apps/kodi/spec.py` now lists the directory and all three
  `Textures13.db*` files adjacent, with a comment, so a future edit does not split them again.
- **Arctic Fuse compiles its shortcut config.** A hub-layout deploy can transfer byte-correctly and
  still render the old layout, because the skin's compiled shortcut XML cache only regenerates under
  specific conditions and does not invalidate just because the source config changed. **Still open:**
  `apps/kodi/transforms/hub_layout.py` writes the skin's `skinvariables-shortcut-*.json` from
  `data/hubs/*.yml`, but nothing in that transform or the deploy path clears the compiled cache or
  forces a restart. Any workflow changing hub layout or HomeSwitcher slots must do both explicitly.

If a deployed device is reported unstable, diff the transferred config against the gold source before
assuming a config regression — and check `logcat` for a **multi-process death cluster** within the
same ~300ms window, which is Android's low-memory killer rather than an app bug. The texture storm
above was one of three compounding causes of a real low-memory kill; a dead MariaDB backend and
bloat apps in DNS-blocked retry loops supplied the other two.

## What can be delivered into a profile

Build transforms edit an extracted profile and `kodi.apply_device_config` sets `id`/value pairs inside
an existing settings XML. For a long time neither could **create a file**, so anything that is a whole
file had no home.

Closed for fleet-wide content — both wired into `apps/kodi/pack.py`'s chain:

| Transform | Module | Driven by |
|---|---|---|
| `ShipFiles` | `apps/kodi/transforms/files.py` | the recipe's `shipped.files` |
| `AddVideoSources` | `apps/kodi/transforms/sources.py` | the recipe's `video_sources.sources`, merged into the captured `sources.xml` |

**Still open: genuinely per-device files.** There is no mechanism, and the hazard is unchanged —
hand-placed files live under the state root, which `restore` replaces **wholesale**. Anything put on a
device by hand is gone at the next deploy, silently. If a file needs to differ per device, reaching
for `ShipFiles` is the wrong answer.

## The library is fleet-wide and needs the network

`advancedsettings.xml` points the video library at MySQL on the router. Two consequences:

- **Library views require the network.** Offline, Kodi cannot reach the database, so the library and
  every `library://` smartlist — including Arctic Fuse's *Recently Added* rows — are unavailable.
  Putting downloads in the library defeats the reason for downloading them.
- **The library is shared.** Scraping a device-local path writes entries every other device can see
  and none can open.

Device-local media belongs in `userdata/sources.xml` only, browsed through **Videos → Files**: local,
no network, per-device. Content type and scraping deliberately unset. Before adding any source to a
Kodi library, check `advancedsettings.xml` for a shared `<videodatabase>`.

That backend is Entware-hosted MariaDB (3306) and SMB (445) on the router, and it fails independently
of fleetctl — so a Kodi symptom that looks like a deploy bug ("watchedlist won't sync", "library is
empty") is very often the shared infrastructure being down. TCP-test both ports on the router before
debugging the pipeline. Three traps when it is down:

1. The init script redirects all output to `/dev/null`, so a failed start produces no visible error
   and `status` just says "not running". Run the daemon binary directly to see why.
2. The Android devices run an always-on VPN tunnel, so testing connectivity *from* a device cannot
   distinguish "server down" from "device can't route there". Test from a machine outside the tunnel.
3. `/opt` is a symlink into a ramdisk that a firmware update wipes, along with the `post-mount` script
   that relinks it at boot — and `post-mount` only runs when JFFS custom scripts are enabled, a toggle
   a firmware update has been seen to silently reset. Check that the toggle is on before concluding
   the symlink is the whole story. A reboot alone does not fix either; the broken state is the
   post-reboot steady state.

## Navigation is TMDbHelper-first

Every hub row, link and menu entry in Arctic Fuse is a TMDbHelper node or widget. Provider addons
(Umbrella, The Crew) are invoked as **players** from TMDbHelper's player dialog and are never browsed
directly. This decides where a UI change belongs:

- What appears in a playback menu comes from TMDbHelper's players
  (`userdata/addon_data/plugin.video.themoviedb.helper/players/*.json`), not the provider's own menu
  settings. Those JSONs are whole files, so `ShipFiles` can deliver them.
- A provider's context-menu options are effectively **dead configuration** — those menus are never
  reached.
- A provider setting still matters when it changes what the provider *does* once invoked (scraping,
  debrid, downloads), just not what is shown.

Reaching for the skin or the hub layout to add a menu entry is the wrong layer.

## Triaging a download that does nothing

An Umbrella download producing no file, no error and no `kodi.log` line has **two** unrelated causes,
and hours went into device, path, permission, keymap and Flatpak theories for both. Neither was ever
the problem.

1. **A confirm dialog is waiting.** `doDownload(..., no_confirm=False)` shows a prompt and does
   nothing until accepted. Dismissing it is not a failure, so there is no file, no error and nothing
   logged — silence meaning "waiting" reads as silence meaning "broken". The same link that had
   "failed" repeatedly downloaded all 370MB the moment the prompt was accepted.
2. **The magnet will not resolve.** `sourcesResolve` pushes the magnet to the debrid service, waits,
   fails, deletes the torrent and returns nothing; `download()` then raises on the empty URL and a
   bare `except` prints the traceback to **stderr, not the Kodi log**. A source shown as `unchecked`
   still offers Download — the menu only hides it for `UNCACHED` — so "Download is offered" does not
   mean "this will resolve".

Cheapest-first ladder:

1. **Look for a blocking dialog** — `DialogConfirm.xml` in `kodi.log`. When a Kodi action produces no
   output at all, a waiting dialog comes before any fault theory.
2. **Read `temp/umbrella.log`**, with `debug.enabled` *and* `debug.level` both set (two separate
   settings under the addon's Debugging category). It logs the resolved URL and destination on
   success, and the resolution failure otherwise.
3. **`curl -sI <resolved url>`** — the downloader aborts without a usable `Content-Length`.
4. **Only then** suspect paths or permissions, and test them from **inside** the sandbox
   (`flatpak run --command=touch tv.kodi.Kodi <path>`) — a host shell can write where the sandbox
   cannot.
5. If the magnet will not resolve, try another source.

Download is only reachable through the "Source Select" player; "Auto Play" resolves and plays
immediately and never shows sources.

## Related

- `.claude/skills/adb-device-ops/SKILL.md` — why a failed device command reports success.
- `.claude/skills/pack-authoring/SKILL.md` — where a fact becomes pack or recipe data.
- `.claude/rules/apps.md` — the ring rules this all has to live inside.
