"""Tests for the Arctic Fuse hub layout transform."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest

from fleetctl.apps.kodi.transforms.hub_layout import ApplyHubLayout, load_layout

SKINVARS = "userdata/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3"
NODES = "userdata/addon_data/plugin.video.themoviedb.helper/nodes"


def _read(profile: Path, relative: str) -> object:
    return json.loads((profile / relative).read_text(encoding="utf-8"))


def test_every_managed_hub_gets_widgets_and_a_node(tmp_path: Path) -> None:
    # Arrange
    transform = ApplyHubLayout()

    # Act
    written = transform.apply(tmp_path, {})

    # Assert
    assert written
    for slot in ("home", "1101", "1102", "1104"):
        assert (tmp_path / SKINVARS / f"skinvariables-shortcut-{slot}widgets.json").is_file()
    for node in ("home_hub.json", "movies_hub_main.json", "tv_hub_main.json", "genres_hub.json"):
        assert (tmp_path / NODES / node).is_file()


def test_unmanaged_slots_are_never_written(tmp_path: Path) -> None:
    """1103 is hand-curated and 1107 is Live TV; both must survive a build."""
    # Act
    ApplyHubLayout().apply(tmp_path, {})

    # Assert
    names = {path.name for path in (tmp_path / SKINVARS).iterdir()}
    assert not [name for name in names if "1103" in name or "1107" in name or "1108" in name]


def test_a_hub_without_a_submenu_writes_no_submenu_file(tmp_path: Path) -> None:
    # Act
    ApplyHubLayout().apply(tmp_path, {})

    # Assert
    assert not (tmp_path / SKINVARS / "skinvariables-shortcut-homesubmenu.json").exists()
    assert (tmp_path / SKINVARS / "skinvariables-shortcut-1101submenu.json").is_file()


def test_submenus_end_with_the_skins_blank_slot(tmp_path: Path) -> None:
    """The skin's own editor writes this "add item" affordance; a generated file must look the same."""
    # Act
    ApplyHubLayout().apply(tmp_path, {})
    submenu = _read(tmp_path, f"{SKINVARS}/skinvariables-shortcut-1102submenu.json")

    # Assert
    assert isinstance(submenu, list)
    assert submenu[-1]["label"] == ""
    assert [group["label"] for group in submenu[:-1]] == ["Genres", "By Network", "International", "By Decade", "Critically Acclaimed"]
    assert all(group["path"] == "Custom_Submenu" for group in submenu[:-1])


def test_icons_resolve_to_real_addon_paths(tmp_path: Path) -> None:
    # Act
    ApplyHubLayout().apply(tmp_path, {})
    widgets = _read(tmp_path, f"{SKINVARS}/skinvariables-shortcut-1101widgets.json")

    # Assert
    assert isinstance(widgets, list)
    assert all(row["icon"].startswith("special://") for row in widgets)
    assert not [row for row in widgets if "{" in row["icon"]]


def test_library_rows_come_first_so_the_screen_paints_before_any_tmdb_call(tmp_path: Path) -> None:
    # Act
    ApplyHubLayout().apply(tmp_path, {})
    widgets = _read(tmp_path, f"{SKINVARS}/skinvariables-shortcut-1101widgets.json")

    # Assert
    assert isinstance(widgets, list)
    assert widgets[0]["path"].startswith("library://")
    assert widgets[1]["path"].startswith("library://")


def test_discover_rows_carry_their_params(tmp_path: Path) -> None:
    # Act
    ApplyHubLayout().apply(tmp_path, {})
    widgets = _read(tmp_path, f"{SKINVARS}/skinvariables-shortcut-1101widgets.json")

    # Assert
    assert isinstance(widgets, list)
    comedy = next(row for row in widgets if row["label"] == "Comedy")
    params = dict(parse_qsl(urlsplit(comedy["path"]).query))
    assert params == {
        "info": "discover",
        "with_id": "True",
        "tmdb_type": "movie",
        "with_genres": "35",
        "sort_by": "popularity.desc",
        "vote_count.gte": "300",
        "widget": "True",
    }


def test_nodes_mirror_the_widgets_and_load_on_select(tmp_path: Path) -> None:
    """A hub's node drifting from its widgets is what this transform exists to prevent."""
    # Act
    ApplyHubLayout().apply(tmp_path, {})
    widgets = _read(tmp_path, f"{SKINVARS}/skinvariables-shortcut-1101widgets.json")
    node = _read(tmp_path, f"{NODES}/movies_hub_main.json")

    # Assert
    assert isinstance(widgets, list) and isinstance(node, dict)
    assert node["name"] == "MOVIES"
    assert [entry["name"] for entry in node["list"][: len(widgets)]] == [row["label"] for row in widgets]
    assert all(entry["widget"] == "False" for entry in node["list"])


def test_the_browse_hub_reuses_the_other_hubs_rows_verbatim(tmp_path: Path) -> None:
    """1104 is an index, not a second definition: a copy here is how the two drifted before."""
    # Act
    ApplyHubLayout().apply(tmp_path, {})
    movies = _read(tmp_path, f"{SKINVARS}/skinvariables-shortcut-1101submenu.json")
    browse = _read(tmp_path, f"{SKINVARS}/skinvariables-shortcut-1104submenu.json")

    # Assert
    assert isinstance(movies, list) and isinstance(browse, list)
    genres = next(group for group in movies if group["label"] == "Genres")
    mirrored = next(group for group in browse if group["label"] == "Movie Genres")
    assert [row["path"] for row in mirrored["submenu"]] == [row["path"] for row in genres["submenu"]]


def test_regenerating_an_unchanged_layout_is_byte_identical(tmp_path: Path) -> None:
    """Guids are derived, not random, so the build's hash check does not re-push an unchanged hub."""
    # Act
    ApplyHubLayout().apply(tmp_path, {})
    first = (tmp_path / SKINVARS / "skinvariables-shortcut-1102submenu.json").read_bytes()
    ApplyHubLayout().apply(tmp_path, {})
    second = (tmp_path / SKINVARS / "skinvariables-shortcut-1102submenu.json").read_bytes()

    # Assert
    assert first == second


def test_every_guid_in_a_file_is_distinct(tmp_path: Path) -> None:
    # Act
    ApplyHubLayout().apply(tmp_path, {})
    submenu = _read(tmp_path, f"{SKINVARS}/skinvariables-shortcut-1101submenu.json")

    # Assert
    assert isinstance(submenu, list)
    guids = [group["guid"] for group in submenu] + [row["guid"] for group in submenu for row in group["submenu"]]
    assert len(guids) == len(set(guids))


def test_an_empty_layout_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setattr("fleetctl.apps.kodi.transforms.hub_layout.load_layout", lambda name: {})

    # Act
    written = ApplyHubLayout().apply(tmp_path, {})

    # Assert
    assert written == []
    assert not (tmp_path / SKINVARS).exists()


def test_the_shipped_layout_defines_the_expected_hubs() -> None:
    # Act
    layout = load_layout()

    # Assert
    assert set(layout["hubs"]) == {"home", "1101", "1102", "1104"}
    assert ApplyHubLayout().name == "apply_hub_layout"
