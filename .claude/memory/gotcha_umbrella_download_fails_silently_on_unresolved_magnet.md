---
name: an Umbrella download dies silently when a magnet will not resolve
description: A spinner that vanishes with no file and no error means Real-Debrid could not resolve that source's magnet; Umbrella's router swallows the exception.
type: project
---

Picking **Download** on a source whose magnet Real-Debrid cannot resolve
produces a busy spinner, a closing context menu, and nothing else — no file,
no dialog, no line in `kodi.log`. The router does:

```python
if caller == 'sources':
    control.busy()
    try:
        downloader.download(name, image, sources.Sources().sourcesResolve(...), title, pack)
    except:
        traceback.print_exc()   # stderr, not the Kodi log
```

`sourcesResolve` pushes the magnet to Real-Debrid, waits, fails, deletes the
torrent, and returns nothing. `download()` then raises on the empty URL and
the bare `except` hides it.

The evidence lives in Umbrella's **own** log, `temp/umbrella.log`, not in
`kodi.log`:

```
FAILED TO RESOLVE MAGNET "…2160p.HDR.Ai.Upscale…"      → spinner, nothing
url: https://…real-debrid.com/d/…ELiTE.mkv             → downloaded, 393MB in 20s
```

A source shown as `unchecked` still offers Download — the menu only hides it
for `UNCACHED` — so "Download is offered" does not mean "this will resolve".

**Why:** every symptom points at the device — paths, permissions, sandboxing,
input mapping — and none of those were ever wrong. Hours went into them.

**How to apply:** when a download does nothing, read
`temp/umbrella.log` first, with `debug.enabled` **and** `debug.level` both set
(there are two settings, under the addon's *Debugging* category). It logs the
resolved URL and destination when it works, and the resolution failure when it
does not. Then simply try another source. See
[[gotcha_umbrella_download_waits_on_a_confirm_dialog]].
