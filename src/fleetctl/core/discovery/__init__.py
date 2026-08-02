"""Finding devices: sweep a network, then let packs claim what they recognize.

Split in two deliberately. Sweeping produces *hosts* — addresses that
answered — and knows nothing about what they are. Claiming turns a host into
a device, and only a pack can do that, because only a pack knows what its own
hardware looks like.

The predecessor fused the two: a host was a device if it answered
`getprop ro.product.model`, which meant a PC or a phone on the subnet was by
definition not a device.
"""

from __future__ import annotations
