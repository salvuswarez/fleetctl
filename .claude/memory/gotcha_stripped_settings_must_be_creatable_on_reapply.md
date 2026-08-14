---
name: stripping build settings requires apply_device_config to create them
description: A device-neutral build removes exactly the settings a device needs to override, so the reapply step must create a missing setting rather than skip it.
type: project
---

`StripDeviceSettings` removes hardware-specific settings from a build, and
`kodi.apply_device_config` puts each device's own values back. The two only
compose if the reapply step can **create** a setting that is not in the file —
the settings a device most needs to override are precisely the ones the strip
removed.

`_apply_file` originally skipped an absent setting, which silently reduced
per-device display calibration to a no-op: `videoscreen.resolution` was
stripped from the build and could never be restored. It now creates the
element.

Related gap, still open: `apply_overscan` has **no production caller**. It is
defined and unit-tested but nothing invokes it, so `overscan` in
`vars.kodi.display` is recorded by `kodi.read_display`, accepted by
`validate_display`, and never applied. Overscan also lives inside the
`<resolutions>` calibration blocks, which the strip removes and which only
Kodi regenerates — so applying it needs Kodi to have launched at least once
after a deploy.

**Why:** each half looked correct alone. The interaction only shows up as a
change count that is quietly lower than expected.

**How to apply:** when adding anything that removes content from a build, check
what is supposed to put it back and confirm that path can handle absence. See
[[gotcha_gold_build_carries_capture_device_display_config]] and
[[gotcha_kodi_setting_default_attribute_discards_override]].
