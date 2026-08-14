---
name: gotcha_home_launcher_cannot_be_set_over_adb
description: set-home-activity and RoleManager both report success over ADB and leave the launcher unchanged; the HOME role needs on-device consent.
metadata:
  type: project
---

A third-party launcher can be **installed** over ADB but cannot be **made the
launcher**. Verified on hardware 2026-08-12 (SHIELD Android TV, Android 11),
with Projectivy 4.71 installed and resolving a valid HOME activity
(`com.spocky.projengmenu/.ui.home.MainActivity`):

| Attempt | Reported | Actual |
|---|---|---|
| `cmd package set-home-activity COMPONENT` | `Success` | unchanged |
| `cmd package set-home-activity --user 0 COMPONENT` | `Success` | unchanged |
| `cmd role add-role-holder --user 0 android.app.role.HOME PKG` | no error | unchanged |
| `cmd role clear-role-holders` then `add-role-holder` | no error | unchanged |

This is Android behaving correctly: silently reassigning HOME over a debug
shell is a launcher-hijack, and the role system requires user consent. Vendor
firmware pins it further.

**Verify behaviourally, never by return value.** Press HOME and read
`dumpsys activity activities | grep mResumedActivity`. Every one of the
commands above is another instance of
[[gotcha_adb_exec_cannot_see_exit_status]] — `Success` printed to stdout for
work that did not happen.

`cmd role` also has no `get-role-holders` on this build (only `add-`,
`remove-`, `clear-role-holders`), so the role cannot be read back at all — the
behavioural check is the *only* evidence available.

**How to apply:** installing a launcher is automatable; selecting it is not.
The remaining steps need a remote: press HOME and pick it from the chooser, or
Settings → Apps → Default apps. A launcher's own preferences live in
`/data/data/<pkg>/shared_prefs/`, which is `Permission denied` for uid 2000
(shell), so an in-launcher setting such as "start app at boot" cannot be
configured over ADB either.

If clearing the HOME role, always re-add a known-good launcher in the **same
command chain** — a dropped connection between clear and add leaves the device
at `FallbackHome`. Related: [[gotcha_android_tv_cannot_autostart_kodi]].
