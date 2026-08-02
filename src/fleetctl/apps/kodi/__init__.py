"""Kodi app pack.

Owns what a Kodi profile *is* and how to shape one. Owns nothing about where
that profile lives on a device, how it is archived, or how bytes get there —
all of that is the device pack's, reached through the `state` verb.

Grep this package for a path or a `tar` and you should find neither.
"""

from __future__ import annotations
