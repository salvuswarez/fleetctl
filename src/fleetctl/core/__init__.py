"""Device-agnostic kernel.

Knows nothing about Fire TV, Shields, PCs, or Kodi. Everything device- or
app-specific lives in ``fleetctl.packs`` or ``fleetctl.apps``, which import
inward. Nothing here may import either.
"""

from __future__ import annotations
