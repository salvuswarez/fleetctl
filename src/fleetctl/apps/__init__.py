"""App packs: software that runs *on* devices.

An app pack may import ``fleetctl.core``. It must never import a device pack:
it declares the capabilities it needs and the engine resolves which pack
provides them. That indirection is what lets one build target several device
types without knowing any of them exist.
"""

from __future__ import annotations
