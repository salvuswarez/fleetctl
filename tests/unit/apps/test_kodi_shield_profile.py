"""The Shield recipe: gold with the 1.7GB stick's limits lifted.

The risk this guards is a Shield-only value leaking into `gold`, where it
would reach every stick in the fleet and reintroduce the low-memory kill the
gold settings exist to prevent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fleetctl.apps.kodi import pack
from fleetctl.apps.kodi.transforms.settings import ApplySettings
from fleetctl.packs.shield.pack import ShieldPack

GUISETTINGS = "guisettings.xml"
SKIN = "addon_data/skin.arctic.fuse.3/settings.xml"


def _recipe(name: str) -> dict[str, Any]:
    return pack._load_profile(name)


def test_the_shield_pack_asks_for_the_shield_recipe() -> None:
    """Without this the hardware resolves to gold and the tuning never
    reaches it."""
    # Act / Assert
    assert ShieldPack().app_profiles["kodi"] == "shield"


def test_the_shield_recipe_ships() -> None:
    # Act / Assert
    assert "shield" in pack.profiles()


def test_the_shield_recipe_inherits_golds_addon_allow_list() -> None:
    """It extends gold rather than restating it, so a fleet-wide addon change
    still reaches the Shield."""
    # Act
    recipe = _recipe("shield")

    # Assert
    assert "skin.arctic.fuse.3" in recipe["prune_addons"]["allow"]
    assert recipe["apply_hub_layout"]["layout"] == "arctic-fuse-3"


def test_the_shield_recipe_raises_the_file_cache() -> None:
    """Kodi 21 moved the cache out of advancedsettings.xml into the GUI, so
    the live value is `filecache.memorysize` -- measured at 32MB on hardware
    while an inert 150MB block sat in advancedsettings.xml."""
    # Act
    settings = _recipe("shield")["apply_settings"]["settings"]

    # Assert
    assert int(settings[GUISETTINGS]["filecache.memorysize"]) > 32


def test_the_shield_recipe_re_enables_hub_preloading() -> None:
    """gold disables it for a 1.7GB stick. That is the stick's constraint."""
    # Act / Assert
    assert _recipe("shield")["apply_settings"]["settings"][SKIN]["startup.enablehubpreloading"] == "true"


def test_gold_keeps_hub_preloading_off_and_names_no_file_cache() -> None:
    """The load-bearing assertion: a Shield value must not reach the sticks."""
    # Act
    gold = _recipe("gold")["apply_settings"]["settings"]

    # Assert
    assert gold[SKIN]["startup.enablehubpreloading"] == "false"
    assert GUISETTINGS not in gold


def test_the_shield_recipe_still_strips_capture_device_settings() -> None:
    """Inherited from gold and must stay: resolution and calibration describe
    the device a capture came from, whatever the recipe."""
    # Act
    strip = _recipe("shield")["strip_device_settings"]

    # Assert
    assert strip["drop_calibration"] is True
    assert "videoscreen.resolution" in strip["settings"]


def test_the_shield_recipe_puts_back_no_audio_settings() -> None:
    """Passthrough describes the receiver a device is plugged into. A build is
    shared, so restoring one device's audio config would strand the others."""
    # Act
    settings = _recipe("shield")["apply_settings"]["settings"]

    # Assert
    assert not [key for entries in settings.values() for key in entries if key.startswith("audiooutput.")]


def test_applying_a_setting_clears_the_default_attribute(tmp_path: Path) -> None:
    """`default="true"` asserts the value IS Kodi's default, and Kodi may
    discard a setting marked that way. Leaving it produces a file that greps
    back correctly and never takes effect."""
    # Arrange
    userdata = tmp_path / "userdata"
    userdata.mkdir()
    (userdata / GUISETTINGS).write_text(
        '<settings version="2"><setting id="filecache.memorysize" default="true">32</setting></settings>',
        encoding="utf-8",
    )

    # Act
    changes = ApplySettings(overrides={GUISETTINGS: {"filecache.memorysize": "200"}}).apply(tmp_path, {})

    # Assert
    written = (userdata / GUISETTINGS).read_text(encoding="utf-8")
    assert changes
    assert "200" in written
    assert 'default="true"' not in written


@pytest.mark.parametrize("profile", ["gold", "shield", "deck"])
def test_every_shipped_profile_resolves(profile: str) -> None:
    """A profile that fails to resolve fails deep in the transform chain."""
    # Act / Assert
    assert pack._chain(_recipe(profile))
