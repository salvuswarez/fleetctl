"""Shared Android behaviour, composed by vendor packs.

Not a pack: it registers nothing and has no entry point. `firetv` and
`shield` each *compose* it and supply their own data and quirks.

Inheritance would be the wrong tool here for a concrete reason. Two of this
project's hardest-won facts — `pm disable-user` silently no-ops on Fire OS
5.x, and toybox `tar -z` produces truncated archives on that build — are
*Amazon's* bugs, not Android's. A `ShieldPack(FireTvPack)` would inherit both
workarounds untested, and the two-step tar they force costs real time on a
large profile.

Quirks arrive as data, and data merges rather than overriding.
"""

from __future__ import annotations
