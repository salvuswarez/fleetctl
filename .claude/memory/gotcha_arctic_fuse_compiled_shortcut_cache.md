---
name: A deploy can look like a no-op because Arctic Fuse caches compiled shortcut XML
description: Pushing new hub/skin config and restarting Kodi is not enough on its own — Arctic Fuse compiles HomeSwitcher/shortcut config into a cached XML form, so a deploy can transfer correctly and still render the old layout until that cache is cleared.
type: gotcha
---

Observed during the hub-redesign work (predecessor repo): a deploy appeared to do nothing — the
device received the new config, but the on-screen layout didn't change. The transferred files were
verified byte-correct against the source; the stale artifact was Arctic Fuse's own compiled shortcut
XML cache, which only regenerates from source config under specific conditions and doesn't
necessarily invalidate itself just because the underlying settings/config file changed.

**Why this matters:** it produces a false "success" — the transfer succeeds, no error is logged
anywhere, and the device is simply still showing the previous layout. Without knowing to check for
this, it reads exactly like "the deploy did nothing," which sends debugging in the wrong direction
(re-checking the transfer, the config generation, the push mechanism — none of which are actually
broken).

**How to apply:** any deploy/refresh workflow that changes hub layout, HomeSwitcher slots, or other
Arctic Fuse skin config must clear the compiled shortcut cache and force a Kodi restart as an
explicit step — not rely on the new config simply "taking effect." A deploy is not verified done
until the on-device UI is re-inspected (a pulled screenshot or live state read) and shown to reflect
the new layout, not just until the transfer step reports success. If `apps/kodi`'s deploy/refresh path
doesn't already invalidate this cache as part of applying hub-layout config, that's a gap worth
closing — see [[gotcha_kodi_texture_index_survives_thumbnail_prune]] for the same shape of bug
(a cache the deploy path doesn't know to also touch).
