---
paths: ["src/fleetctl/packs/**"]
---

# Device Pack Rules

A device pack answers two questions: *what is this device* and *what can I do to it*.

1. **Compose `packs/android`, never subclass it** — `firetv` and `shield` share ADB behaviour but not vendor bugs. Inheritance would force the Shield to inherit Fire OS workarounds it may not need.
2. **Vendor quirks live in the pack that has them, as data** — not in `core/`, not in a sibling pack, not as a global assumption.
3. **Declare capabilities honestly** — a capability you declare is a promise the engine schedules against. Under-declaring is safe; over-declaring fails mid-run on real hardware.
4. **Every action declares its effect class** — `READ`, `MUTATING`, or `DESTRUCTIVE`. The policy layer keys off this, so a mislabelled destructive action silently bypasses approval.
5. **Package lists, prune paths and probe strings are `data/*.yml`** — not Python constants. That is what makes a second vendor a config change.
6. **Verify against real hardware before claiming support** — the predecessor project inherited a borrowed bloat list that contained fabricated package names. Document what was tested versus inferred.
7. **A probe returns `None` when it doesn't recognize a host** — never a partially-filled identity. Claiming is ordered; the wrong pack claiming a host is worse than no pack claiming it.
8. **Nothing here imports `apps/`** — a device pack does not know Kodi exists.
