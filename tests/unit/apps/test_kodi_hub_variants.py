"""Layout inheritance, and the Deck's extra download rows."""

from __future__ import annotations

import pytest

from fleetctl.apps.kodi.pack import KodiApp
from fleetctl.apps.kodi.transforms.hub_layout import load_layout
from fleetctl.core.errors import FleetError

DECK_LAYOUT = "arctic-fuse-3-deck"
SHARED_LAYOUT = "arctic-fuse-3"
DOWNLOAD_PATHS = {"/run/media/deck/SC400/kodi/TVShows/", "/run/media/deck/SC400/kodi/Movies/"}


def _home_widgets(layout: str) -> list[dict[str, object]]:
    """RETURNS: list[dict[str, object]]: The home hub's widget rows for a layout."""
    return list(load_layout(layout)["hubs"]["home"]["widgets"])


def test_the_deck_layout_appends_the_download_rows() -> None:
    # Act
    paths = {row.get("path") for row in _home_widgets(DECK_LAYOUT)}

    # Assert
    assert DOWNLOAD_PATHS <= paths


def test_the_shared_layout_has_no_device_local_paths() -> None:
    """A row pointing at one device's SD card is dead on every other device."""
    # Act
    paths = {str(row.get("path", "")) for row in _home_widgets(SHARED_LAYOUT)}

    # Assert
    assert not [path for path in paths if "/run/media" in path]


def test_appending_keeps_every_inherited_row() -> None:
    """A plain merge would replace the list; the whole point is to add."""
    # Act
    shared, deck = _home_widgets(SHARED_LAYOUT), _home_widgets(DECK_LAYOUT)

    # Assert
    assert deck[: len(shared)] == shared
    assert len(deck) == len(shared) + 2


def test_the_rest_of_the_layout_is_inherited_untouched() -> None:
    # Act
    shared, deck = load_layout(SHARED_LAYOUT), load_layout(DECK_LAYOUT)

    # Assert
    assert set(deck["hubs"]) == set(shared["hubs"])
    assert deck["icons"] == shared["icons"]
    assert deck["hubs"]["1101"] == shared["hubs"]["1101"]


def test_the_resolved_layout_drops_its_own_directives() -> None:
    # Act
    resolved = load_layout(DECK_LAYOUT)

    # Assert
    assert "extends" not in resolved
    assert "add_widgets" not in resolved


def test_adding_to_an_unknown_hub_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silently dropping the rows would ship a profile missing the menu the
    recipe asked for."""
    # Arrange
    import fleetctl.apps.kodi.transforms.hub_layout as module

    monkeypatch.setattr(module, "_read_layout", lambda name: {"hubs": {"home": {"widgets": []}}, "add_widgets": {"9999": [{"label": "x"}]}})

    # Act / Assert
    with pytest.raises(FleetError, match="unknown hub"):
        load_layout("whatever")


def test_a_layout_that_extends_itself_is_rejected() -> None:
    # Act / Assert
    with pytest.raises(FleetError, match="extends itself"):
        load_layout(DECK_LAYOUT, _seen=(SHARED_LAYOUT, DECK_LAYOUT))


def test_the_deck_profile_uses_the_deck_layout() -> None:
    # Act
    hub = [transform for transform in KodiApp("deck").transforms if transform.name == "apply_hub_layout"][0]

    # Assert
    assert hub.layout == DECK_LAYOUT  # type: ignore[attr-defined]


def test_the_gold_profile_still_uses_the_shared_layout() -> None:
    # Act
    hub = [transform for transform in KodiApp("gold").transforms if transform.name == "apply_hub_layout"][0]

    # Assert
    assert hub.layout == SHARED_LAYOUT  # type: ignore[attr-defined]
