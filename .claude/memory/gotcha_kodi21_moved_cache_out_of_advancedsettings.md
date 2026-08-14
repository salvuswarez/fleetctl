---
name: gotcha_kodi21_moved_cache_out_of_advancedsettings
description: Kodi 21 Omega removed the advancedsettings.xml cache block; the live value is filecache.memorysize in guisettings.xml, and the old block is silently inert.
metadata:
  type: project
---

Kodi 21 Omega moved caching out of `advancedsettings.xml` into GUI settings.
The `<cache><buffermode>/<memorysize>/<readfactor></cache>` block is **still
parsed without complaint and does nothing.**

Measured on hardware 2026-08-12 (Kodi 21.3, SHIELD):

| Where | Value | Effect |
|---|---|---|
| `advancedsettings.xml` `<cache><memorysize>` | 157286400 (150MB) | **inert** |
| `guisettings.xml` `filecache.memorysize` | 32 (MB) | live |

So a profile carrying careful cache tuning was actually running a 32MB cache.
The live setting had **no `default` attribute**, meaning it was deliberately
set once — probably before the move — and then orphaned.

Kodi reserves roughly **3x** `memorysize` in RAM, so budget against measured
free memory, not total.

Related settings that also live in `guisettings.xml`, not advancedsettings:
`filecache.buffermode`, `filecache.readfactor`, `filecache.chunksize`.

**How to apply:** tune the cache through `apply_settings` on
`guisettings.xml`. Do not add a `<cache>` block to `advancedsettings.xml` and
do not trust one you find there — check the Kodi version first. That file is
still load-bearing for other things: on this fleet it holds the **MySQL
`<videodatabase>` block**, so it must be merged into, never replaced. See
[[reference_kodi_shared_router_backend]] and
[[gotcha_shared_mysql_library_defeats_offline_downloads]].

**A second trap sits next to this.** `ApplySettings` in
`transforms/settings.py` did not clear `default="true"` when writing a value,
unlike `device_config._apply_file` which had already been fixed — two
implementations, one correct. Any guisettings key still at its default (e.g.
`videoscreen.10bitsurfaces`) would have been written and then discarded by
Kodi. Fixed; a test now asserts the attribute is gone.
See [[gotcha_kodi_setting_default_attribute_discards_override]].
