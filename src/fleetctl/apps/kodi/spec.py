"""What Kodi's state is — the app's half of the `state` contract."""

from __future__ import annotations

from ...core.state import AppStateSpec

APP_ID = "kodi"

# Top-level entries that constitute a Kodi profile. A restore replaces exactly
# these, and a build archive carries exactly these at its root — flat, with no
# wrapping directory, so it extracts straight into the state root.
PROFILE_MEMBERS: tuple[str, ...] = ("addons", "userdata", "media")

# Caches and derived data dropped before a capture. All regenerated on demand.
#
# The texture database is listed for a non-obvious reason: it indexes the
# thumbnail files pruned above it by path and hash. Carrying it without the
# files it references leaves a freshly-restored device with a fully populated
# index pointing at nothing, and Kodi then burns a burst of redundant network
# and disk activity at startup reconciling dead references — observed
# contributing to a low-memory kill on a 1.7GB device. Dropping it lets the
# cache rebuild lazily instead.
CAPTURE_EXCLUDE: tuple[str, ...] = (
    "userdata/Thumbnails",
    "userdata/Database/Textures13.db",
    "userdata/Database/Textures13.db-wal",
    "userdata/Database/Textures13.db-shm",
    "addons/temp",
    "temp",
    "log",
)

# Package identifiers per platform. A device pack looks up its own.
IDENTIFIERS = {"android": "org.xbmc.kodi"}

# Kodi keeps its profile in a dotted directory inside the app's data area.
# Where that data area *is* is the device pack's business.
STATE_SUBDIR = ".kodi"


def state_spec(*, exclude: tuple[str, ...] = CAPTURE_EXCLUDE) -> AppStateSpec:
    """Describe Kodi's state to whichever device pack holds it.

    **PARAMETERS:**
        `exclude` (tuple[str, ...], optional): Paths to drop before capture. Defaults to `CAPTURE_EXCLUDE`. Pass an empty tuple to capture a profile verbatim.  <br>

    **RETURNS:**
        `AppStateSpec`: The spec a device pack's state manager consumes.  <br>
    """
    return AppStateSpec(
        app_id=APP_ID,
        identifiers=IDENTIFIERS,
        app_root=STATE_SUBDIR,
        members=PROFILE_MEMBERS,
        exclude=exclude,
    )
