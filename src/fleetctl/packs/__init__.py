"""Device packs: what a device *is*, and what you can do to it.

A pack may import ``fleetctl.core``. It must not import ``fleetctl.apps``,
and it must not import a sibling pack — except ``fleetctl.packs.android``,
which is a shared collaborator library rather than a pack: it registers
nothing, has no entry point, and is composed by the vendor packs that use it.
"""

from __future__ import annotations
