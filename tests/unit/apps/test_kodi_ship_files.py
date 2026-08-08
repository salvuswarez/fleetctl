"""Placing whole files into a profile that no capture contained."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleetctl.apps.kodi.pack import KodiApp
from fleetctl.apps.kodi.transforms.files import ShipFiles
from fleetctl.core.errors import FleetError

KEYMAP = "steamdeck-keymap.xml"
DESTINATION = "userdata/keymaps/steamdeck.xml"


def test_a_shipped_file_is_written_into_the_profile(tmp_path: Path) -> None:
    # Act
    changes = ShipFiles(files={DESTINATION: KEYMAP}).apply(tmp_path, {})

    # Assert
    written = tmp_path / DESTINATION
    assert written.is_file()
    assert b"ContextMenu" in written.read_bytes()
    assert changes == [f"added {DESTINATION} ({written.stat().st_size} bytes)"]


def test_missing_parent_directories_are_created(tmp_path: Path) -> None:
    """`userdata/keymaps/` does not exist in a captured profile."""
    # Act
    ShipFiles(files={DESTINATION: KEYMAP}).apply(tmp_path, {})

    # Assert
    assert (tmp_path / "userdata" / "keymaps").is_dir()


def test_an_existing_file_is_replaced_and_says_so(tmp_path: Path) -> None:
    # Arrange
    existing = tmp_path / DESTINATION
    existing.parent.mkdir(parents=True)
    existing.write_text("stale", encoding="utf-8")

    # Act
    changes = ShipFiles(files={DESTINATION: KEYMAP}).apply(tmp_path, {})

    # Assert
    assert existing.read_text(encoding="utf-8") != "stale"
    assert changes[0].startswith("replaced")


def test_nothing_configured_is_a_clean_no_op(tmp_path: Path) -> None:
    # Act / Assert
    assert ShipFiles().apply(tmp_path, {}) == []


@pytest.mark.parametrize("destination", ["/etc/passwd", "../../escape.xml", "userdata/../../escape.xml"])
def test_a_destination_outside_the_profile_is_refused(tmp_path: Path, destination: str) -> None:
    """A recipe is hand-edited config; a build must not write outside the tree
    it was handed."""
    # Act / Assert
    with pytest.raises(FleetError, match="profile-relative|escapes the profile"):
        ShipFiles(files={destination: KEYMAP}).apply(tmp_path, {})


def test_a_source_that_does_not_ship_fails_the_build(tmp_path: Path) -> None:
    """Silently skipping would deploy a profile missing the file the recipe
    asked for, and nothing downstream would notice."""
    # Act / Assert
    with pytest.raises(FleetError, match="does not ship"):
        ShipFiles(files={DESTINATION: "no-such-file.xml"}).apply(tmp_path, {})


def test_config_overrides_the_instance_mapping(tmp_path: Path) -> None:
    # Act
    ShipFiles(files={}).apply(tmp_path, {"files": {DESTINATION: KEYMAP}})

    # Assert
    assert (tmp_path / DESTINATION).is_file()


def test_the_deck_profile_ships_the_keymap() -> None:
    """Without it the keymap is placed by hand and wiped by the next deploy."""
    # Act
    chain = {transform.name: transform for transform in KodiApp("deck").transforms}

    # Assert
    assert "ship_files" in chain
    assert DESTINATION in dict(chain["ship_files"].files)  # type: ignore[attr-defined]


def test_the_gold_profile_ships_nothing() -> None:
    """A Fire Stick has neither touchscreen nor gamepad; the transform is only
    added when a recipe asks for it."""
    # Act
    chain = [transform.name for transform in KodiApp("gold").transforms]

    # Assert
    assert "ship_files" not in chain


def test_shipping_runs_before_settings_are_applied() -> None:
    """So a shipped file can then be adjusted, rather than overwriting the
    adjustment."""
    # Act
    chain = [transform.name for transform in KodiApp("deck").transforms]

    # Assert
    assert chain.index("ship_files") < chain.index("apply_settings")
