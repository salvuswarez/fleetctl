"""NVIDIA Shield device pack.

Composes `packs.android` exactly as `packs.firetv` does, and subclasses
neither. The Fire OS workarounds — the split tar, the netcat upload, the
verify-after-disable — are Amazon's bugs; this pack declares none of them and
takes the stock-Android paths until someone measures otherwise on hardware.

That is the point of the composition rule, and this pack is where it is
tested rather than asserted.
"""

from __future__ import annotations
