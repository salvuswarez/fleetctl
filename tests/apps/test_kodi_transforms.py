"""Tests for the profile transforms and per-device configuration."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from fleetctl.apps.kodi.device_config import apply_device_config, validate_display
from fleetctl.apps.kodi.transforms.advanced import RemoveThumbnailSubstitution
from fleetctl.apps.kodi.transforms.view_types import ApplyViewTypes
from fleetctl.core.errors import FleetError
from fleetctl.core.inventory.device import Device
from fleetctl.core.transport.fake import FakeTransport

ADVANCED = """<advancedsettings>
  <pathsubstitution>
    <substitute><from>special://thumbnails/</from><to>smb://nas/thumbs/</to></substitute>
    <substitute><from>special://logs/</from><to>smb://nas/logs/</to></substitute>
  </pathsubstitution>
</advancedsettings>"""

VIEWS = """<includes>
  <expression name="Exp_View_505">old</expression>
  <expression name="Exp_View_521">old</expression>
</includes>"""


def _profile(root: Path, *, advanced: str | None = None, views: str | None = None) -> Path:
    (root / "userdata").mkdir(parents=True, exist_ok=True)
    if advanced is not None:
        (root / "userdata" / "advancedsettings.xml").write_text(advanced, encoding="utf-8")
    if views is not None:
        target = root / "addons" / "skin.example" / "1080i"
        target.mkdir(parents=True, exist_ok=True)
        (target / "views.xml").write_text(views, encoding="utf-8")
    return root


def test_a_thumbnail_substitution_is_removed(tmp_path: Path) -> None:
    """Caching artwork over a network share turns every read into network
    I/O, which contributed to a low-memory kill."""
    # Arrange
    profile = _profile(tmp_path, advanced=ADVANCED)

    # Act
    changes = RemoveThumbnailSubstitution().apply(profile, {})

    # Assert
    assert len(changes) == 1
    remaining = (profile / "userdata" / "advancedsettings.xml").read_text(encoding="utf-8")
    assert "thumbnails" not in remaining
    assert "logs" in remaining  # unrelated substitutions are left alone


def test_an_emptied_substitution_block_is_removed(tmp_path: Path) -> None:
    # Arrange
    only = ADVANCED.replace("<substitute><from>special://logs/</from><to>smb://nas/logs/</to></substitute>", "")
    profile = _profile(tmp_path, advanced=only)

    # Act
    RemoveThumbnailSubstitution().apply(profile, {})

    # Assert
    assert "pathsubstitution" not in (profile / "userdata" / "advancedsettings.xml").read_text(encoding="utf-8")


def test_a_profile_without_advanced_settings_is_not_an_error(tmp_path: Path) -> None:
    assert RemoveThumbnailSubstitution().apply(_profile(tmp_path), {}) == []


def test_unparseable_advanced_settings_are_left_alone(tmp_path: Path) -> None:
    """Corrupting a file we could not read would be worse than skipping it."""
    # Arrange
    profile = _profile(tmp_path, advanced="<not valid xml")

    # Act / Assert
    assert RemoveThumbnailSubstitution().apply(profile, {}) == []


def test_view_expressions_are_replaced(tmp_path: Path) -> None:
    # Arrange
    profile = _profile(tmp_path, views=VIEWS)
    transform = ApplyViewTypes(includes_path="skin.example/1080i/views.xml", expressions={"Exp_View_505": "new value"})

    # Act
    changes = transform.apply(profile, {})

    # Assert
    assert len(changes) == 1
    assert "new value" in (profile / "addons" / "skin.example" / "1080i" / "views.xml").read_text(encoding="utf-8")


def test_an_expression_the_skin_does_not_have_is_skipped(tmp_path: Path) -> None:
    # Arrange
    profile = _profile(tmp_path, views=VIEWS)
    transform = ApplyViewTypes(includes_path="skin.example/1080i/views.xml", expressions={"Exp_View_999": "x"})

    # Act / Assert
    assert transform.apply(profile, {}) == []


def test_a_different_skin_is_not_an_error(tmp_path: Path) -> None:
    """A profile using another skin should build, not fail."""
    # Arrange
    transform = ApplyViewTypes(includes_path="skin.other/1080i/views.xml", expressions={"Exp_View_505": "x"})

    # Act / Assert
    assert transform.apply(_profile(tmp_path), {}) == []


def test_view_types_does_nothing_when_unconfigured(tmp_path: Path) -> None:
    assert ApplyViewTypes().apply(_profile(tmp_path, views=VIEWS), {}) == []


@pytest.mark.parametrize(
    "display",
    [{}, {"resolution_index": "eighteen"}, {"overscan": {"left": "zero"}}],
)
def test_malformed_display_config_is_rejected(display: dict[str, Any]) -> None:
    """It is hand-edited in the inventory, so it is checked rather than
    trusted."""
    with pytest.raises(FleetError):
        validate_display(display)


@pytest.mark.parametrize(
    "display",
    [{"resolution_index": 18}, {"overscan": {"left": 0, "right": 1920}}, {"resolution_index": 18, "overscan": {"top": 4}}],
)
def test_well_formed_display_config_is_accepted(display: dict[str, Any]) -> None:
    validate_display(display)


def test_a_device_with_no_config_is_a_clean_no_op(device_context: Any) -> None:
    """Most devices are identical and want the shared build unchanged."""
    # Arrange
    context = device_context(FakeTransport())

    # Act
    result = apply_device_config(context)

    # Assert
    assert result.facts["changes"] == 0


def test_per_device_settings_are_pulled_edited_and_pushed_back(device_context: Any, tmp_path: Path) -> None:
    """Done by file transfer rather than an on-device sed, so a value with
    XML-significant characters cannot corrupt the file."""
    # Arrange
    settings = '<settings><setting id="audiooutput.channels">2</setting></settings>'
    root = "/sdcard/Android/data/org.xbmc.kodi/files/.kodi"
    transport = FakeTransport(responses={f"{root}/userdata/guisettings.xml": settings})
    device = Device(
        id="stick-1",
        type="firetv",
        address="192.168.1.50",
        vars={"kodi": {"settings": {"guisettings.xml": {"audiooutput.channels": "1"}}}},
    )
    context = replace(device_context(transport), device=device)

    # Act
    result = apply_device_config(context)

    # Assert
    assert result.facts["changes"] == 1
    assert any(call.kind == "put" for call in transport.calls)
