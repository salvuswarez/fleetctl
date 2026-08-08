"""Clearing Kodi's caches on a live device."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from fleetctl.apps.kodi.caches import CACHE_GLOBS, CACHE_PATHS, TRIM_CACHES, trim_caches
from fleetctl.apps.kodi.spec import CAPTURE_EXCLUDE
from fleetctl.core.effects import Effect
from fleetctl.core.transport.fake import FakeTransport

ROOT = "/sdcard/Android/data/org.xbmc.kodi/files/.kodi"


def _present(paths: tuple[str, ...]) -> dict[str, str]:
    """RETURNS: dict[str, str]: Scripted output making each path exist."""
    return {f"test -e {ROOT}/{path} && echo yes": "yes" for path in paths}


def test_the_step_is_declared_destructive() -> None:
    """It deletes. A mislabelled destructive step bypasses approval."""
    # Act / Assert
    assert TRIM_CACHES.effect is Effect.DESTRUCTIVE


def test_the_cache_set_covers_everything_a_capture_drops() -> None:
    """A path worth excluding from a build is worth clearing on a device."""
    # Act / Assert
    assert CACHE_PATHS == CAPTURE_EXCLUDE


def test_addon_packages_are_cleared() -> None:
    """Downloaded install zips; Kodi refetches one if it needs it again."""
    # Act / Assert
    assert "addons/packages" in CACHE_PATHS


def test_crash_logs_are_matched_rather_than_listed() -> None:
    """They carry timestamps, and sit at the profile root — outside the
    members a capture archives, so the capture set never reached them."""
    # Act / Assert
    assert CACHE_GLOBS == ("kodi_crashlog-*.log",)


def test_globs_are_deleted_with_find_not_a_shell_glob(device_context: Any) -> None:
    """Arguments are quoted, which stops the shell expanding `*` — a quoted
    pattern matches a literal filename and removes nothing."""
    # Arrange
    pattern = "kodi_crashlog-*.log"
    listing = f"{ROOT}/kodi_crashlog-20260807_081904.log\n{ROOT}/kodi_crashlog-20260807_190401.log"
    transport = FakeTransport(responses={f"find {ROOT} -maxdepth 1 -name '{pattern}' -type f": listing})
    context = device_context(transport)

    # Act
    result = trim_caches(context)

    # Assert
    assert f"find {ROOT} -maxdepth 1 -name '{pattern}' -type f -delete" in transport.commands()
    assert f"{pattern} (2)" in result.facts["removed"]


def test_the_texture_index_goes_with_the_thumbnails(device_context: Any) -> None:
    """The texture database indexes the thumbnails beside it. Removing one
    without the other leaves an index pointing at files that are gone."""
    # Act / Assert
    assert "userdata/Thumbnails" in CACHE_PATHS
    assert "userdata/Database/Textures13.db" in CACHE_PATHS


def test_present_paths_are_removed(device_context: Any) -> None:
    # Arrange
    transport = FakeTransport(responses=_present(CACHE_PATHS))
    context = device_context(transport)

    # Act
    result = trim_caches(context)

    # Assert
    assert result.facts["removed"] == list(CACHE_PATHS)
    assert f"rm -rf {ROOT}/userdata/Thumbnails" in transport.commands()


def test_absent_paths_are_not_removed_or_reported(device_context: Any) -> None:
    """A freshly deployed profile has none of these; a miss is normal."""
    # Arrange
    transport = FakeTransport(responses=_present(("temp",)))
    context = device_context(transport)

    # Act
    result = trim_caches(context)

    # Assert
    assert result.facts["removed"] == ["temp"]
    assert not [command for command in transport.commands() if command.startswith("rm -rf") and "Thumbnails" in command]


def test_it_touches_nothing_outside_the_profile_root(device_context: Any) -> None:
    """Every path is joined to the state root the pack resolved."""
    # Arrange
    transport = FakeTransport(responses=_present(CACHE_PATHS))

    # Act
    trim_caches(device_context(transport))

    # Assert
    deletions = [command for command in transport.commands() if command.startswith("rm -rf")]
    assert deletions
    assert all(command.startswith(f"rm -rf {ROOT}/") for command in deletions)


def test_no_user_data_is_in_the_cache_set() -> None:
    """A profile member is user state; clearing one would be a data loss bug."""
    # Act / Assert
    assert not [path for path in CACHE_PATHS if path in ("addons", "userdata", "media")]


def test_a_recipe_can_narrow_what_is_cleared(device_context: Any) -> None:
    # Arrange
    transport = FakeTransport(responses=_present(("temp",)))
    context = replace(device_context(transport), config={"cache_paths": ["temp"]})

    # Act
    result = trim_caches(context)

    # Assert
    assert result.facts["removed"] == ["temp"]


def test_reclaimed_space_is_reported(device_context: Any) -> None:
    # Arrange
    transport = FakeTransport(responses=_present(CACHE_PATHS))

    # Act
    result = trim_caches(device_context(transport))

    # Assert
    assert "reclaimed_bytes" in result.facts
    assert result.facts["free_bytes"] == transport.free_space
