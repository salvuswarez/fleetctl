"""Tests for reading a device's live Kodi display calibration."""

from __future__ import annotations

from pathlib import Path

from fleetctl.apps.kodi.device_config import parse_display

GUISETTINGS = """<settings version="2">
  <setting id="videoscreen.resolution">18</setting>
  <resolutions>
    <resolution>
      <overscan><left>38</left><top>21</top><right>1242</right><bottom>699</bottom></overscan>
    </resolution>
  </resolutions>
</settings>"""


def test_resolution_and_overscan_are_both_read() -> None:
    # Act
    found = parse_display(GUISETTINGS)

    # Assert
    assert found["resolution_index"] == 18
    assert found["overscan"] == {"left": 38, "top": 21, "right": 1242, "bottom": 699}


def test_an_uncalibrated_device_reports_nothing_rather_than_failing() -> None:
    """Kodi only writes a setting that differs from its default, so a device
    nobody has calibrated genuinely has neither value."""
    # Act / Assert
    assert parse_display('<settings version="2"></settings>') == {}


def test_unreadable_or_absent_guisettings_is_not_an_error() -> None:
    # Act / Assert
    assert parse_display("") == {}
    assert parse_display("   ") == {}
    assert parse_display("<settings><broken>") == {}


def test_a_negative_resolution_index_is_kept() -> None:
    """Kodi uses -1 for "not set"; that is a real value, not a parse failure."""
    # Act
    found = parse_display('<settings><setting id="videoscreen.resolution">-1</setting></settings>')

    # Assert
    assert found["resolution_index"] == -1


def test_resolution_without_overscan_omits_the_key() -> None:
    # Act
    found = parse_display('<settings><setting id="videoscreen.resolution">7</setting></settings>')

    # Assert
    assert found == {"resolution_index": 7}


def test_overscan_survives_a_write_read_round_trip(tmp_path: Path) -> None:
    """The writer targeted <resolution> directly while the fields live under
    <resolution><overscan>, so overscan silently never reached a device."""
    # Arrange
    from fleetctl.apps.kodi.device_config import apply_overscan

    path = tmp_path / "guisettings.xml"
    path.write_text(GUISETTINGS, encoding="utf-8")

    # Act
    changed = apply_overscan(path, {"left": 10, "top": 20, "right": 1900, "bottom": 1060})

    # Assert
    assert changed is True
    assert parse_display(path.read_text(encoding="utf-8"))["overscan"] == {"left": 10, "top": 20, "right": 1900, "bottom": 1060}
