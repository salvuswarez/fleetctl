"""Profile transforms: pure changes to an extracted Kodi profile.

Each takes a directory and configuration, mutates the directory, and returns
a description of what it did. No I/O beyond that directory, no transport, no
device. That is what makes ~700 lines of the predecessor's least-testable
logic into fixture-directory tests.

These run in `build`, never `deploy` — structurally, since a deploy step is
handed a transport and no transform chain.
"""

from __future__ import annotations
