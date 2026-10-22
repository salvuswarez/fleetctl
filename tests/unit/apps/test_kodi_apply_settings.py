"""Tests for the Kodi `apply_settings` transform."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import pytest

from fleetctl.apps.kodi.transforms.settings import ApplySettings

SKIN = "addon_data/skin.example/settings.xml"


def _write(profile: Path, body: str) -> Path:
    path = profile / "userdata" / SKIN
    path.parent.mkdir(parents=True)
    path.write_text(f'<?xml version="1.0" encoding="utf-8"?>\n<settings version="2">{body}</settings>', encoding="utf-8")
    return path


def _setting(path: Path, setting_id: str) -> ElementTree.Element:
    found = ElementTree.parse(path).getroot().find(f"setting[@id='{setting_id}']")
    assert found is not None
    return found


@pytest.mark.parametrize(
    ("existing", "expected_type"),
    [
        ('<setting id="homeswitcher.1101.mode" type="string">Combined</setting>', "string"),
        ('<setting id="max_threads">10</setting>', None),
    ],
    ids=["skin-settings-are-typed", "addon-settings-are-not"],
)
def test_a_created_setting_follows_the_files_own_typing(tmp_path: Path, existing: str, expected_type: str | None) -> None:
    """A skin reads typed entries; an untyped spotlight path written into a skin's file would be skipped."""
    # Arrange
    path = _write(tmp_path, existing)
    transform = ApplySettings(overrides={SKIN: {"homeswitcher.1106.toggle": "true"}})

    # Act
    transform.apply(tmp_path, {})

    # Assert
    created = _setting(path, "homeswitcher.1106.toggle")
    assert created.text == "true"
    assert created.get("type") == expected_type


def test_a_value_with_ampersands_round_trips(tmp_path: Path) -> None:
    """Spotlight paths are plugin URLs full of `&`; the XML must escape them, not truncate at them."""
    # Arrange
    path = _write(tmp_path, '<setting id="x" type="string"></setting>')
    url = "plugin://plugin.video.themoviedb.helper/?info=airing_today&tmdb_type=tv&widget=true"

    # Act
    ApplySettings(overrides={SKIN: {"x": url}}).apply(tmp_path, {})

    # Assert
    assert _setting(path, "x").text == url
