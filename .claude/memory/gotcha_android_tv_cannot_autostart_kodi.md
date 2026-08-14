---
name: gotcha_android_tv_cannot_autostart_kodi
description: Kodi declares no HOME activity and Android TV exposes no boot-to-app setting, so launching Kodi at boot needs an external trigger, not a device setting.
metadata:
  type: project
---

There is no way to make Kodi start at boot on an Android TV device through
ADB. Checked on hardware 2026-08-12:

- Kodi's only exported activity is `org.xbmc.kodi/.Splash`, carrying
  `DEFAULT` and `BROWSABLE` — **no `HOME` category**, so it cannot be set as
  the launcher.
- Only `com.google.android.tvlauncher` and `com.android.tv.settings` answer a
  `HOME` intent query.
- `settings get` for `secure boot_to_app`, `global boot_to_app` and
  `secure default_home` all return `null`; the platform exposes no such key.

Running at boot requires an app holding a `BOOT_COMPLETED` receiver, which
means installing a third-party autostart APK. Do not promise autostart as a
fleetctl feature.

**The third-party autostart category is dead, by platform design.** Android 10
(API 29) restricts starting activities from the background, and Android TV
builds are more aggressive still about apps that listen for boot events. So
this is policy, not app quality:

- `news.androidtv.launchonboot` (Launch-On-Boot, MIT, 183 stars) has open,
  unfixed issues titled *"Doesn't work on Android 10"*, *"Does not work on
  Android tv version 11"* and *"Android 12 … not working"*. Last push
  2022-03-03; the newest release carrying an APK is from **2017**. Do not
  recommend it.
- FLauncher (GPL, GitLab, `me.efesser.flauncher`) is free, FOSS and maintained
  but has **no boot-to-app feature** — categories, wallpaper, clock only. Its
  forks (Arc, LtvLauncher) are cosmetic.
- A HOME launcher is the only reliable mechanism, because it is the foreground
  app at boot and therefore exempt. Projectivy has it behind a paid tier.

**ADB is not affected by that restriction**, which is why `kodi.launch` works:
`am start` from an adb shell is not a background app start. Verified on
hardware — Kodi was force-stopped and relaunched successfully.

**A set-top box never leaves the network while asleep.** Verified on hardware
2026-08-12: after `KEYCODE_SLEEP`, ping, TCP/5555 and ADB all kept answering
for a full minute, and `mWakefulness` read `Asleep` over ADB throughout. So a
ping or `device_tracker` trigger **never transitions** and an automation built
on one looks correct and silently never fires. Use `mWakefulness`, exposed by
`Toolkit.device_power`.

**Android reports four wakefulness states, not two.** `Dreaming` means the
screensaver is up — the device is on and may already be playing something.
Observed live: an idle Shield read `dreaming`, not `awake`. An automation
firing on every `off -> on` therefore also fires when a screensaver exits,
which would yank the foreground away from whatever was playing. Condition on
the raw state (`from_state.attributes.power_state == 'asleep'`) to catch only
a real wake from sleep.

**How to apply:** the supported path is an **external trigger** calling
`kodi.launch`, which resolves the launch activity generically
(`cmd package resolve-activity --brief`, leanback category first, then
launcher) and then verifies with `pidof` — `am start` reports failure on
stdout and [[gotcha_adb_exec_cannot_see_exit_status]] means the command layer
cannot tell.

From Home Assistant that trigger is the `fleetctl.run_step` **service**. Note
the integration's websocket commands serve the panel only and are unreachable
from an automation or script — the service exists specifically to close that
gap. Related: [[gotcha_ha_regenerates_fleet_yml_every_setup]].
