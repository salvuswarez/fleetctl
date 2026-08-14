---
name: a Kodi setting keeping default="true" may discard its override
description: Writing a new value while leaving default="true" produces a change that reads back correctly and does not take effect; clear the attribute.
type: project
---

In Kodi's settings XML, `default="true"` asserts the value equals the addon's
default, and Kodi is free to discard a setting marked that way on load. Writing
a non-default value without clearing the attribute leaves a file that greps
back exactly as intended and has no effect:

```xml
<setting id="downloads" default="true">true</setting>   <!-- ignored -->
<setting id="downloads">true</setting>                  <!-- applied -->
```

`_apply_file` in `apps/kodi/device_config.py` now pops the attribute whenever
it changes a value. Settings that were already non-default carry no attribute,
which is why per-device overrides of `videoplayer.*` worked while the first
attempt at Umbrella's `downloads` did not.

**Why:** it is invisible to verification. Every check short of launching Kodi
and observing behaviour reports success.

**How to apply:** when overriding an addon setting, confirm the written element
has no `default` attribute. Note the transform only rewrites a file when a
value actually changes, so re-running it will not repair an
already-correct-looking value — reset the setting first, then apply. See
[[reference_kodi_navigation_is_tmdbhelper_first]].
