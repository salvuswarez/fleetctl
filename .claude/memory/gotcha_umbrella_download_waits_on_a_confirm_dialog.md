---
name: an Umbrella download blocks on a confirm dialog
description: doDownload runs with no_confirm=False and waits for an on-screen prompt; declining or ignoring it produces no file, no error and no log line.
type: project
---

`downloader.doDownload(..., no_confirm=False)` shows a confirmation dialog and
does nothing until it is accepted. Dismissing it is not a failure, so there is
**no file, no error dialog, and nothing in `kodi.log`** — indistinguishable
from a broken download.

Verified 2026-08-07 on a Steam Deck: the same Real-Debrid link that had
"failed" repeatedly downloaded all 370,759,124 bytes the moment the prompt was
accepted, matching the `Content-Length` measured with `curl -sI`.

Diagnosing a Kodi download that appears to do nothing, cheapest first:

1. `curl -sI <resolved url>` — `doDownload` aborts unless there is a response
   with a usable `Content-Length`.
2. Check for `DialogConfirm.xml` in `kodi.log` — that is the prompt waiting.
3. Only then suspect paths or permissions; test those from **inside** the
   sandbox (`flatpak run --command=touch tv.kodi.Kodi <path>`), since a host
   shell can write where the sandbox cannot.

A download can also be triggered without any UI at all: Umbrella's router has
an `easynews` caller that passes `url` straight to the downloader with no
debrid resolution, reachable over JSON-RPC via `Addons.ExecuteAddon`.

**Why:** hours went into path, permission, keymap and Flatpak theories for a
prompt nobody had accepted. Silence read as failure when it meant "waiting".

**How to apply:** when a Kodi action produces no output at all, look for a
blocking dialog before assuming a fault. See
[[reference_kodi_navigation_is_tmdbhelper_first]].
