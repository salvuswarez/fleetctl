"""Tests for reading a device's Kodi and skin versions."""

from __future__ import annotations

from fleetctl.apps.kodi.health import _ADDON_VERSION


def test_the_skin_version_is_read_from_its_addon_tag() -> None:
    # Arrange
    xml = '<?xml version="1.0"?>\n<addon id="skin.arctic.fuse.3" name="Arctic Fuse 3" provider-name="jurialmunkey" version="3.2.15">'

    # Act
    match = _ADDON_VERSION.search(xml)

    # Assert
    assert match is not None and match.group(1) == "3.2.15"


def test_a_nested_import_version_is_not_mistaken_for_the_skin_version() -> None:
    """addon.xml lists <import version="..."> for every dependency; only the
    <addon> tag's own version describes the skin."""
    # Arrange
    xml = '<addon id="skin.arctic.fuse.3" version="3.2.15">\n  <requires><import addon="xbmc.gui" version="5.17.0" /></requires>'

    # Act
    match = _ADDON_VERSION.search(xml)

    # Assert
    assert match is not None and match.group(1) == "3.2.15"


def test_an_absent_skin_reports_nothing_rather_than_failing() -> None:
    # Act / Assert
    assert _ADDON_VERSION.search("") is None
    assert _ADDON_VERSION.search("/system/bin/sh: cat: not found") is None
