"""Fire TV device pack.

Composes `packs.android` and supplies its own data: the bloat list, the
maintenance settings, and the Fire OS quirks. It subclasses nothing — the
quirks it declares are Amazon's bugs, and a sibling vendor pack must not
inherit them untested.
"""

from __future__ import annotations
