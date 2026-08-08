"""Stripping one device's hardware config out of a shared build.

The fixture below is the real shape read off a Steam Deck on 2026-08-06 after
a Fire Stick build was deployed to it: a mode index from another machine, and
calibration blocks carrying a zero refresh rate.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

from fleetctl.apps.kodi.pack import KodiApp
from fleetctl.apps.kodi.transforms.device_settings import StripDeviceSettings

GUI_SETTINGS = """<?xml version="1.0" encoding="utf-8"?>
<settings version="2">
    <setting id="videoscreen.resolution">18</setting>
    <setting id="videoscreen.monitor" default="true">Default</setting>
    <setting id="videoscreen.screen" default="true">0</setting>
    <setting id="videoscreen.dither" default="true">false</setting>
    <setting id="audiooutput.audiodevice">AUDIOTRACK:AudioTrack (RAW)|Android IEC packer</setting>
    <setting id="audiooutput.passthroughdevice">AUDIOTRACK:AudioTrack (RAW)|Android IEC packer</setting>
    <setting id="audiooutput.passthrough">true</setting>
    <setting id="audiooutput.channels" default="true">1</setting>
    <setting id="lookandfeel.skin">skin.arctic.fuse.3</setting>
    <resolutions>
        <resolution>
            <description>1920x1080 @ 60.000004 - Full Screen</description>
            <refreshrate>0.000000</refreshrate>
            <overscan><left>0</left><top>0</top><right>1920</right><bottom>1080</bottom></overscan>
        </resolution>
        <resolution>
            <description>3840x2160 @ 59.939999 - Full Screen</description>
            <refreshrate>0.000000</refreshrate>
            <overscan><left>0</left><top>0</top><right>1920</right><bottom>1080</bottom></overscan>
        </resolution>
    </resolutions>
</settings>
"""


@pytest.fixture
def profile(tmp_path: Path) -> Path:
    """RETURNS: Path: An extracted profile carrying a Fire Stick's GUI settings."""
    userdata = tmp_path / "userdata"
    userdata.mkdir(parents=True)
    (userdata / "guisettings.xml").write_text(GUI_SETTINGS, encoding="utf-8")
    return tmp_path


def _ids(profile: Path) -> set[str]:
    """RETURNS: set[str]: Every setting id remaining in the profile's GUI settings."""
    root = ElementTree.parse(profile / "userdata" / "guisettings.xml").getroot()
    return {element.get("id") or "" for element in root.iter("setting")}


def test_the_capture_devices_mode_index_is_removed(profile: Path) -> None:
    """A mode index names an unrelated mode on any other hardware."""
    # Act
    StripDeviceSettings().apply(profile, {})

    # Assert
    assert "videoscreen.resolution" not in _ids(profile)


def test_display_calibration_is_removed_entirely(profile: Path) -> None:
    """Every captured block carried `refreshrate 0.000000`, which is a zero
    handed straight to Kodi's frame-duration maths on a mismatched panel."""
    # Act
    changes = StripDeviceSettings().apply(profile, {})

    # Assert
    root = ElementTree.parse(profile / "userdata" / "guisettings.xml").getroot()
    assert root.find("resolutions") is None
    assert any("calibration" in change for change in changes)


def test_the_android_audio_devices_are_removed(profile: Path) -> None:
    # Act
    StripDeviceSettings().apply(profile, {})

    # Assert
    remaining = _ids(profile)
    assert "audiooutput.audiodevice" not in remaining
    assert "audiooutput.passthroughdevice" not in remaining


def test_passthrough_is_removed_because_kodi_does_not_fix_it(profile: Path) -> None:
    """Kodi's ValidateOutputDevices rewrites the two device strings at startup
    but leaves this one, stranding a handheld passing through to an absent
    receiver."""
    # Act
    StripDeviceSettings().apply(profile, {})

    # Assert
    assert "audiooutput.passthrough" not in _ids(profile)


def test_settings_that_are_not_hardware_specific_survive(profile: Path) -> None:
    """Stripping the skin or the channel layout would be a silent regression."""
    # Act
    StripDeviceSettings().apply(profile, {})

    # Assert
    remaining = _ids(profile)
    assert "lookandfeel.skin" in remaining
    assert "audiooutput.channels" in remaining
    assert "videoscreen.dither" in remaining


def test_the_file_stays_valid_xml(profile: Path) -> None:
    # Act
    StripDeviceSettings().apply(profile, {})

    # Assert
    root = ElementTree.parse(profile / "userdata" / "guisettings.xml").getroot()
    assert root.tag == "settings"


def test_a_recipe_can_narrow_what_is_stripped(profile: Path) -> None:
    """The list is data, so a profile can tune it without a code change."""
    # Act
    StripDeviceSettings().apply(profile, {"settings": ["videoscreen.resolution"], "drop_calibration": False})

    # Assert
    remaining = _ids(profile)
    assert "videoscreen.resolution" not in remaining
    assert "audiooutput.passthrough" in remaining
    assert ElementTree.parse(profile / "userdata" / "guisettings.xml").getroot().find("resolutions") is not None


def test_a_profile_without_gui_settings_is_not_an_error(tmp_path: Path) -> None:
    # Act / Assert
    assert StripDeviceSettings().apply(tmp_path, {}) == []


def test_unparseable_settings_do_not_fail_the_build(tmp_path: Path) -> None:
    """A build failing on one malformed file would strand the whole fleet."""
    # Arrange
    userdata = tmp_path / "userdata"
    userdata.mkdir(parents=True)
    (userdata / "guisettings.xml").write_text("<settings><broken>", encoding="utf-8")

    # Act / Assert
    assert StripDeviceSettings().apply(tmp_path, {}) == []


def test_applying_twice_is_stable(profile: Path) -> None:
    """A rebuild from an already-stripped profile must not error."""
    # Act
    StripDeviceSettings().apply(profile, {})
    second = StripDeviceSettings().apply(profile, {})

    # Assert
    assert second == []


@pytest.mark.parametrize("name", ["gold", "deck"])
def test_every_shipped_profile_strips_device_settings(name: str) -> None:
    """A build is one artifact for the whole fleet; carrying one device's
    calibration is never correct, so no profile may opt out by omission."""
    # Act
    chain = [transform.name for transform in KodiApp(name).transforms]

    # Assert
    assert "strip_device_settings" in chain


def test_stripping_runs_before_settings_are_applied() -> None:
    """So a recipe that deliberately pins one of these keys still wins."""
    # Act
    chain = [transform.name for transform in KodiApp("gold").transforms]

    # Assert
    assert chain.index("strip_device_settings") < chain.index("apply_settings")
