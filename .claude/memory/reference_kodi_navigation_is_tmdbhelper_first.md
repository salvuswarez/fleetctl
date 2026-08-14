---
name: all Kodi navigation routes through TMDbHelper
description: In the Arctic Fuse setup every link and menu comes from TMDbHelper; provider addons are only ever reached as players, never browsed directly.
type: reference
---

Navigation in this fleet's Kodi profile is **TMDbHelper-first**. Every hub row,
link and menu entry in Arctic Fuse is a TMDbHelper node or widget. Provider
addons (Umbrella, The Crew) are invoked as *players* from TMDbHelper's player
dialog and are not browsed directly.

Consequences when changing behaviour:

- What appears in a playback menu is decided by TMDbHelper's **players**
  (`userdata/addon_data/plugin.video.themoviedb.helper/players/*.json`), not by
  the provider's own menu settings.
- A provider's context-menu options (`context.umbrella.*`) are effectively dead
  configuration — those menus are never reached.
- A provider setting still matters when it changes what the provider does once
  invoked (scraping, debrid, downloads), just not what is *shown*.
- Umbrella's download is a context-menu action inside its source-results
  window, so it is only reachable through the "Source Select" player. The
  "Auto Play" player resolves and plays immediately and never shows sources.

**Why:** it decides where a UI change belongs. Reaching for the skin or the hub
layout to add a menu entry is the wrong layer, and provider menu settings look
like the right knob while doing nothing.

**How to apply:** to change what a playback menu offers, look at the TMDbHelper
player JSONs first. See [[project_steamdeck_kodi_pack_plan]].
