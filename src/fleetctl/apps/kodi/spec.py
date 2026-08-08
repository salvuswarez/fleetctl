"""What Kodi's state is — the app's half of the `state` contract."""

from __future__ import annotations

from ...core.state import AppStateSpec

APP_ID = "kodi"

# The recipe used when nothing names another. It lives here rather than in
# `pack` so `steps` can read it without importing the pack that imports it:
# a build published before profiles were recorded can only have been made
# with this one, because the entry point could construct no other.
DEFAULT_PROFILE = "gold"

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
    # Downloaded addon install zips. Kodi refetches one if it ever needs it
    # again, so shipping them in a build is dead weight.
    "addons/packages",
    "temp",
    "log",
)

# Package identifiers per platform. A device pack looks up its own.
#
# The Linux identifier is the Flathub application id, verified against a
# SteamOS 3.8 device on 2026-08-06.
IDENTIFIERS = {"android": "org.xbmc.kodi", "linux": "tv.kodi.Kodi"}

# Where Kodi keeps its profile *within* the data area a pack resolves — which
# is Kodi's own business and differs per platform:
#
#   android  `.kodi` inside the app's external files directory.
#   linux    nothing. Under Flatpak the sandboxed data directory *is* the
#            profile: `addons/`, `userdata/` and `media/` sit directly in it,
#            with no `.kodi` wrapper. Confirmed on hardware — assuming `.kodi`
#            here would write a profile into a directory Kodi never reads.
STATE_SUBDIRS = {"android": ".kodi", "linux": ""}


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
        app_roots=STATE_SUBDIRS,
        members=PROFILE_MEMBERS,
        exclude=exclude,
    )
