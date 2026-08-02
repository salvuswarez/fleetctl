"""Storing and retrieving the things fleetctl moves around.

Captures, built profiles, base images. The seam owns naming and resolution
as well as bytes — otherwise every app pack reimplements "find the newest
build" and "reject a reference pointing outside its directory".
"""

from __future__ import annotations
