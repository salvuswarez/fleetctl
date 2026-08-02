"""Talking to a device.

`Transport` is the seam every side effect passes through, which is what lets
auditing be a decorator rather than an obligation on every caller.
"""

from __future__ import annotations
