---
name: borrowed package lists contain fabricated entries
description: A bloat list inherited from another codebase was spot-checked against a real device's `pm list packages` and found to mix real package names with invented ones. Verify against hardware before shipping a list.
type: project
---

The predecessor project inherited a `BLOAT_PACKAGES` list from a sibling codebase. Spot-checking it against a real device's `pm list packages` dump found **fabricated and wrong entries mixed in with real ones** — names that resembled plausible Amazon packages but did not exist on any device, alongside near-misses where the real package had a different namespace segment. The user's own assessment of the source: *"i just dont trust that code."*

**Why:** A wrong entry is not merely inert. It makes a debloat step report work it did not do, and it makes the list look authoritative to the next reader — who then propagates it further.

**How to apply:** Every package list shipped in a pack's `data/*.yml` must be verified against a real device's `pm list packages` output, and the pack's docs must state what was **verified on hardware** versus **inferred**. This is a public project (D8) — someone else will run these lists against their own devices. Treat any list arriving from outside this repo as unverified until checked. See [[gotcha_pm_disable_by_fireos_version]] for why verification of *effect* matters too.
