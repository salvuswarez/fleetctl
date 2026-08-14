---
name: an entry-point app is constructed with no arguments
description: KodiApp's profile parameter was unreachable from HA, so every panel build silently used gold; per-run selection has to come from the composition root.
type: project
---

`registry.discover()` loads packs with `entry.load()()` — no arguments. So the
one registered `KodiApp` is always `KodiApp(profile="gold")`, and its `profile`
constructor parameter is reachable only by code that builds its own instance
(a script, a test). Nothing in the HA path does.

The consequence was invisible: `kodi.build` took a `source` and no profile, so
a Steam Deck capture built through the Fleet Ops panel produced a **gold**
image — ARM addon binaries the Deck cannot execute, plus the display settings
behind the SIGFPE. It looked like it worked. Only the script that constructed
`KodiApp(profile="deck")` directly ever produced a correct Deck build.

The fix is shaped by where the knowledge lives:

- The **device pack** declares `app_profiles` (`{"kodi": "deck"}`). Hardware is
  the reason, so the pack that knows the hardware states it.
- The **composition root** (`cli/main.py:_transforms_for`) resolves it, because
  the decision needs the artifact store (which device a capture came from), the
  inventory, and the pack — no single ring holds all three. Order: explicit
  flag, then `device.vars.kodi.profile`, then the pack's default.
- The **app pack** gains `transforms_for(name)` and stays device-agnostic.

The resolved name is written onto the build's metadata, and `deploy` uses it
two ways: it refuses a build shaped for other hardware, and when no build is
named it picks the newest one *matching this device's profile* rather than the
newest overall. Both matter because `kodi-refresh` deploys to a mixed fleet
without naming a build — publishing one Deck build made the Deck image the
newest, and every Fire Stick would have received it.

Two rules keep this total rather than advisory:

- **Every device resolves to a definite profile** — device vars, then pack,
  then the app's own default. An earlier version fell through to *empty*, and
  a device with no profile has nothing to disagree with: the guard protected
  the Deck but let a deck build reach a Fire Stick.
- **A build with no recorded profile counts as the default.** Not a guess — a
  build predating this could only have been made with the default, since the
  entry point could construct no other app. Legacy artifacts stay deployable
  to the devices they were always right for, and are refused elsewhere.

**Why:** an extension point loaded by entry point can carry no per-run
configuration. Anything that varies per run has to arrive as a step parameter
or be resolved by the composition root.

**How to apply:** when adding a constructor parameter to a pack or app, ask how
HA would ever set it. If the answer is "it can't", the parameter is a test-only
affordance. See [[gotcha_gold_build_carries_capture_device_display_config]] and
[[gotcha_transport_cannot_answer_for_pack_capabilities]].
