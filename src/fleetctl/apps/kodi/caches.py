"""Clearing Kodi's regenerable caches on a live device."""

from __future__ import annotations

import logging
import posixpath
import shlex

from fleetctl.apps.kodi.spec import APP_ID, CAPTURE_EXCLUDE, state_spec
from fleetctl.core.effects import Capability, Effect
from fleetctl.core.workflow.step import DeviceStepContext, StepResult, StepSpec

LOGGER = logging.getLogger(__name__)

# Everything a capture drops, for the same reason: it regenerates on demand,
# and the texture database indexes the thumbnails beside it — pruning one
# without the other leaves an index pointing at files that are gone, which
# Kodi then works through at startup.
CACHE_PATHS: tuple[str, ...] = CAPTURE_EXCLUDE

# Crash logs accumulate at the profile root, outside the members a capture
# archives, so the capture set was never going to reach them. Matched rather
# than listed because each carries a timestamp.
CACHE_GLOBS: tuple[str, ...] = ("kodi_crashlog-*.log",)

TRIM_CACHES = StepSpec(
    id="kodi.trim_caches",
    summary="Delete Kodi's regenerable caches on a device: thumbnails, the texture index, and temp.",
    effect=Effect.DESTRUCTIVE,
    requires=frozenset({Capability.EXEC, Capability.STATE}),
    scope="device",
)


def trim_caches(context: DeviceStepContext) -> StepResult:
    """Remove Kodi's caches from a device's live profile.

    Nothing here is user data — every path regenerates. A device whose
    thumbnail cache has grown without bound gets it back without a redeploy.

    **PARAMETERS:**
        `context` (DeviceStepContext): The device, its resolved state manager, and config. May supply `cache_paths`.  <br>

    **RETURNS:**
        `StepResult`: What was removed and how much space came back.  <br>
    """
    root = context.state.state_root(state_spec())
    paths = tuple(context.config.get("cache_paths") or CACHE_PATHS)

    before = context.transport.free_bytes(root)
    context.handle.log(f"Clearing {len(paths)} cache path(s) under {root}...")

    removed: list[str] = []
    for relative in paths:
        context.handle.check_cancelled()
        target = posixpath.join(root, relative)
        # Absent paths are the normal case on a freshly deployed profile, so
        # this reports what it acted on rather than failing on a miss.
        if context.transport.exec_ok(f"test -e {shlex.quote(target)} && echo yes", effect=Effect.READ).strip():
            context.transport.exec_ok(f"rm -rf {shlex.quote(target)}", effect=Effect.DESTRUCTIVE)
            removed.append(relative)

    # `find -delete` rather than a shell glob: every argument here is quoted,
    # which stops the remote shell expanding `*` — a quoted pattern matches a
    # literal filename, so the command succeeds and removes nothing.
    for pattern in tuple(context.config.get("cache_globs") or CACHE_GLOBS):
        context.handle.check_cancelled()
        matched = context.transport.exec_ok(f"find {shlex.quote(root)} -maxdepth 1 -name {shlex.quote(pattern)} -type f", effect=Effect.READ)
        if matched.strip():
            context.transport.exec_ok(f"find {shlex.quote(root)} -maxdepth 1 -name {shlex.quote(pattern)} -type f -delete", effect=Effect.DESTRUCTIVE)
            removed.append(f"{pattern} ({len(matched.splitlines())})")

    after = context.transport.free_bytes(root)
    reclaimed = max(after - before, 0)
    context.handle.log(f"Removed {len(removed)} path(s), reclaimed {reclaimed // (1024 * 1024)}MB")
    return StepResult(
        summary=f"{context.device.id}: cleared {len(removed)} {APP_ID} cache path(s), reclaimed {reclaimed // (1024 * 1024)}MB",
        facts={"removed": removed, "reclaimed_bytes": reclaimed, "free_bytes": after},
    )
