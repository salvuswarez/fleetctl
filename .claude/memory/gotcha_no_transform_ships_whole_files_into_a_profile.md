---
name: nothing ships a whole file into a Kodi profile
description: Transforms edit files that already exist and apply_device_config sets key/values; neither can add a new file, so keymaps and sources.xml cannot be delivered.
type: project
---

Two delivery mechanisms exist for Kodi profile content and neither can create
a file:

- **Build transforms** edit an extracted profile — `PruneAddons`,
  `ApplySettings`, `StripDeviceSettings` and friends all modify what the
  capture already contained.
- **`kodi.apply_device_config`** sets `id`/value pairs inside an existing
  settings XML (it can now create a missing `<setting>`, but not a file).

So anything that is a *whole file* has no home:

| Wanted | Path |
|---|---|
| Video sources so downloads land in the library | `userdata/sources.xml` |
| Controller/touch bindings | `userdata/keymaps/*.xml` |
| TMDbHelper custom players | `userdata/addon_data/plugin.video.themoviedb.helper/players/*.json` |

These currently have to be placed by hand, and a deploy wipes them — they live
under the state root, which `restore` replaces wholesale.

**Why:** the gap is invisible until something needs it, and then it looks like
a transform is missing rather than a whole category of delivery.

**How to apply:** a `ShipFiles`-style transform that writes files from profile
data into the extracted tree would close it for fleet-wide content, and is the
right layer — transforms go in build. Genuinely per-device files would need a
different mechanism. See
[[gotcha_stripped_settings_must_be_creatable_on_reapply]].
