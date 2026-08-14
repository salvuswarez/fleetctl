---
name: a gold build carries the capture device's display and audio config
description: guisettings.xml in a build holds the source device's resolution index, calibration blocks and audio devices; harmless across identical Fire Sticks, fatal on different hardware.
type: project
---

`kodi.build` produces one artifact for the whole fleet, but the
`userdata/guisettings.xml` inside it is taken verbatim from **one device's**
capture. It carries that device's hardware configuration:

| Setting | Value from a Fire Stick capture |
|---|---|
| `videoscreen.resolution` | `18` — a *mode index*, meaningless on other hardware |
| `<resolutions>` calibration | 21 blocks, all 1920x1080 / 3840x2160, **every one with `<refreshrate>0.000000</refreshrate>`** |
| `audiooutput.audiodevice` | `AUDIOTRACK:AudioTrack (RAW)|Android IEC packer` |
| `audiooutput.passthroughdevice` | same Android device |
| `audiooutput.passthrough` | `true` (explicitly set, not a default) |

Across a fleet of identical sticks this is invisible — every device has the
same panel and the same Android audio stack. Deployed to a Steam Deck
(1280x800 @ 90Hz, ALSA/PulseAudio) on 2026-08-06 it produced **zero**
calibration entries matching the real panel, and Kodi died with **SIGFPE**
(arithmetic fault, `/app/lib/kodi/kodi.bin`) seconds after opening a 4K
HEVC 23.976fps stream.

Kodi self-heals *some* of this: `ValidateOutputDevices` rewrote both Android
audio device strings to real ALSA ones at startup. It does **not** correct
`videoscreen.resolution`, the calibration blocks, or `audiooutput.passthrough`.

## The design gap

`kodi.apply_device_config` exists for exactly this and runs last in
`kodi-refresh.yml` ("anything that differs per device is reapplied here — the
restored profile overwrote it"). But it **only overlays** `device.vars.kodi`;
its first branch returns early when a device has no vars:

```python
if not display and not settings:
    return StepResult(summary=f"{context.device.id}: no per-device config", ...)
```

So a device with no `vars.kodi` — any newly-added device — silently keeps the
**capture source's** hardware settings. Overlaying is not the same as
neutralising, and nothing in the pipeline neutralises.

**Why:** it is a whole class of bug the fleet's homogeneity has been hiding.
It will bite any non-Fire-Stick target, and it bit the first one tried.

## Fixed

`StripDeviceSettings` (`apps/kodi/transforms/device_settings.py`) runs in every
build, between `prune_addons` and `apply_settings`, driven by
`strip_device_settings` in the profile recipe. It removes the settings above
and the `<resolutions>` block so Kodi re-detects the real hardware;
`apply_device_config` then layers a device's own values on top. Unconditional —
no recipe can opt out by omission.

Note the exact faulting instruction was never confirmed: `coredumpctl` reported
the corefile inaccessible, and Kodi's own crashlog says "gdb not installed,
can't get stack trace". SIGFPE plus a zero refresh rate in the matched
calibration entry is strong circumstantial evidence, not proof. The fix
removes the whole class regardless.

**Side effect worth knowing:** a device with no `vars.kodi.display` now gets
Kodi's own detection rather than silently inheriting the gold stick's overscan.
That is correct, but it is a behaviour change for any Fire Stick relying on
that inheritance.

See [[project_steamdeck_kodi_pack_plan]] and [[feedback_gold_device_protection]].
