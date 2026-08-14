---
name: a shared MySQL library cannot serve offline downloads
description: The fleet's video library lives in MySQL on the router, so library views need the network and a device-local path scraped into it breaks on every other device.
type: project
---

`advancedsettings.xml` points the video library at MySQL on the router
(`192.168.1.1:3306`). Two consequences shape where downloaded media can live:

- **Library views require the network.** Offline, Kodi cannot reach the
  database, so the library and every `library://` smartlist — including
  Arctic Fuse's *Recently Added* rows — are unavailable. Putting downloads in
  the library defeats the reason for downloading them.
- **The library is fleet-wide.** Scraping a device-local path such as
  `/run/media/deck/SC400/kodi/` writes entries every other device can see and
  none can open.

Device-local media therefore belongs in `userdata/sources.xml` only, browsed
through **Videos → Files**. That file is local, needs no network, and is
per-device. Content type and scraping are deliberately not set.

**Why:** "add it to the library so it shows in Recently Added" is the obvious
move and is wrong here in two independent ways. Both only surface if you check
where the library actually lives.

**How to apply:** before adding a source to a Kodi library, check
`advancedsettings.xml` for a shared `<videodatabase>`. If present, treat the
library as fleet-wide network state. See
[[reference_kodi_shared_router_backend]] and
[[gotcha_no_transform_ships_whole_files_into_a_profile]].
