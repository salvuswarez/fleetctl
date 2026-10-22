"""Tests for the Arctic Fuse hub layout transform."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pytest

from fleetctl.apps.kodi.transforms.hub_layout import ApplyHubLayout, load_layout
from fleetctl.core.errors import FleetError

SKINVARS = "userdata/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3"
NODES = "userdata/addon_data/plugin.video.themoviedb.helper/nodes"
MANAGED = ("home", "1101", "1102", "1104")


def _read(profile: Path, relative: str) -> Any:
    return json.loads((profile / relative).read_text(encoding="utf-8"))


def _widgets(profile: Path, slot: str) -> list[dict[str, Any]]:
    widgets: list[dict[str, Any]] = _read(profile, f"{SKINVARS}/skinvariables-shortcut-{slot}widgets.json")
    return widgets


def _row(widgets: list[dict[str, Any]], label: str) -> dict[str, Any]:
    return next(row for row in widgets if row["label"] == label)


# Everything an icon may point at, read off a Shield's installed addons on
# 2026-10-22. TMDbHelper 6.18 ships exactly these; `trending.png` is not one,
# and every entry that named it rendered as a blank tile.
TMDB_ICONS = {
    "airing.png", "cast.png", "config.png", "default.png", "discover.png", "download.png", "episodes.png", "folder.png",
    "genre.png", "images.png", "intheatres.png", "movies.png", "nextpage.png", "popular.png", "randomise.png",
    "recommended.png", "refresh.png", "reviews.png", "save.png", "saveas.png", "search.png", "settings.png",
    "similar.png", "tags.png", "toprated.png", "trakt.png", "trash.png", "tv.png", "upcoming.png",
}  # fmt: skip
SKIN_ICONS = {"calendar.png", "clock-rotate-left.png", "earth-asia.png", "fire.png", "gem.png", "genre.png", "rocket.png", "trophy.png"}
GENRE_ICONS = {
    "action and adventure.jpg", "animation.jpg", "anime.jpg", "comedy.jpg", "crime.jpg", "documentary.jpg", "drama.jpg",
    "family.jpg", "horror.jpg", "reality.jpg", "sci-fi.jpg", "thriller.jpg",
}  # fmt: skip
STUDIO_LOGOS = {
    "a24.png", "abs-cbn entertainment.png", "adult swim.png", "amazon prime video.png", "amc.png", "apple tv+.png",
    "disney+.png", "fx.png", "gma.png", "hbo max.png", "hulu.png", "marvel studios.png", "netflix.png", "paramount+.png",
    "peacock.png", "pixar.png", "showtime.png", "studio ghibli.png",
}  # fmt: skip
KNOWN = {
    "special://home/addons/plugin.video.themoviedb.helper/resources/icons/themoviedb/": TMDB_ICONS,
    "special://skin/extras/icons/": SKIN_ICONS,
    "resource://resource.images.moviegenreicons.white/": GENRE_ICONS,
    "resource://resource.images.studios.coloured/": STUDIO_LOGOS,
}


def _params(row: dict[str, Any]) -> dict[str, str]:
    return dict(parse_qsl(urlsplit(row["path"]).query))


def _menu(profile: Path, slot: str, label: str) -> list[dict[str, Any]]:
    """RETURNS: list[dict[str, Any]]: The rows of one ▶ menu group."""
    return _group(_read(profile, f"{SKINVARS}/skinvariables-shortcut-{slot}submenu.json"), label)


def _group(submenu: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = next(group for group in submenu if group["label"] == label)["submenu"]
    return rows


@pytest.fixture(name="profile")
def _profile(tmp_path: Path) -> Path:
    ApplyHubLayout().apply(tmp_path, {})
    return tmp_path


# --- files and structure ---------------------------------------------------


def test_every_managed_hub_gets_widgets_and_a_node(tmp_path: Path) -> None:
    # Act
    written = ApplyHubLayout().apply(tmp_path, {})

    # Assert
    assert written
    for slot in MANAGED:
        assert (tmp_path / SKINVARS / f"skinvariables-shortcut-{slot}widgets.json").is_file()
    for node in ("home_hub.json", "movies_hub_main.json", "tv_hub_main.json", "genres_hub.json"):
        assert (tmp_path / NODES / node).is_file()


def test_unmanaged_slots_are_never_written(profile: Path) -> None:
    """1103 is hand-curated and 1107 is Live TV; both must survive a build."""
    # Act
    names = {path.name for path in (profile / SKINVARS).iterdir()}

    # Assert
    assert not [name for name in names if "1103" in name or "1107" in name or "1108" in name]


def test_a_hub_that_owns_no_submenu_leaves_the_skins_file_alone(tmp_path: Path) -> None:
    """Home's menu is the skin's own; the layout has no `submenu` key for it."""
    # Arrange
    skin_owned = tmp_path / SKINVARS / "skinvariables-shortcut-homesubmenu.json"
    skin_owned.parent.mkdir(parents=True)
    skin_owned.write_text('[{"label": "$LOCALIZE[3]"}]', encoding="utf-8")

    # Act
    ApplyHubLayout().apply(tmp_path, {})

    # Assert
    assert skin_owned.read_text(encoding="utf-8") == '[{"label": "$LOCALIZE[3]"}]'


def test_an_empty_submenu_replaces_one_left_by_the_capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Skipping the file left Browse's four duplicate menus on Discover after a real deploy."""
    # Arrange
    stale = tmp_path / SKINVARS / "skinvariables-shortcut-1104submenu.json"
    stale.parent.mkdir(parents=True)
    stale.write_text('[{"label": "Movie Genres", "path": "Custom_Submenu"}]', encoding="utf-8")
    layout = {"hubs": {"1104": {"node": "d.json", "node_name": "D", "widgets": [], "submenu": []}}}
    monkeypatch.setattr("fleetctl.apps.kodi.transforms.hub_layout.load_layout", lambda name: layout)

    # Act
    ApplyHubLayout().apply(tmp_path, {})

    # Assert
    submenu = _read(tmp_path, f"{SKINVARS}/skinvariables-shortcut-1104submenu.json")
    assert [group["label"] for group in submenu] == [""]


def test_submenus_end_with_the_skins_blank_slot(profile: Path) -> None:
    """The skin's own editor writes this "add item" affordance; a generated file must look the same."""
    # Act
    submenu = _read(profile, f"{SKINVARS}/skinvariables-shortcut-1102submenu.json")

    # Assert
    assert submenu[-1]["label"] == ""
    assert [group["label"] for group in submenu[:-1]] == ["Genres", "Networks", "International", "By Decade", "Collections"]
    assert all(group["path"] == "Custom_Submenu" for group in submenu[:-1])


def test_every_icon_names_a_file_that_ships(profile: Path) -> None:
    """A missing icon renders as a blank tile with no error anywhere; this is the only place it can be caught."""
    # Arrange
    widgets = [row for slot in MANAGED for row in _widgets(profile, slot)]
    submenus = [_read(profile, f"{SKINVARS}/skinvariables-shortcut-{slot}submenu.json") for slot in ("1101", "1102", "1104")]
    icons = {row["icon"] for row in widgets}
    icons |= {item["icon"] for submenu in submenus for group in submenu for item in [group, *group.get("submenu", [])]}

    # Act
    unknown = sorted(icon for icon in icons - {""} if not any(icon.startswith(prefix) and icon[len(prefix) :] in names for prefix, names in KNOWN.items()))

    # Assert
    assert unknown == []


def test_genres_and_networks_get_their_own_icons(profile: Path) -> None:
    """A generic film strip on every genre and binoculars on every network told you nothing (seen on a Shield)."""
    # Act
    genres = {row["label"]: row["icon"] for row in _menu(profile, "1101", "Genres")}
    networks = {row["label"]: row["icon"] for row in _menu(profile, "1102", "Networks")}

    # Assert
    assert genres["Horror"] == "resource://resource.images.moviegenreicons.white/horror.jpg"
    assert networks["Netflix"] == "resource://resource.images.studios.coloured/netflix.png"
    assert len(set(genres.values())) == len(genres)
    assert len(set(networks.values())) == len(networks)


def test_regenerating_an_unchanged_layout_is_byte_identical(tmp_path: Path) -> None:
    """Guids are derived, not random, so the build's hash check does not re-push an unchanged hub."""
    # Act
    ApplyHubLayout().apply(tmp_path, {})
    first = (tmp_path / SKINVARS / "skinvariables-shortcut-1101widgets.json").read_bytes()
    ApplyHubLayout().apply(tmp_path, {})
    second = (tmp_path / SKINVARS / "skinvariables-shortcut-1101widgets.json").read_bytes()

    # Assert
    assert first == second


@pytest.mark.parametrize("slot", MANAGED)
def test_every_guid_in_a_hub_is_distinct(profile: Path, slot: str) -> None:
    # Act
    widgets = _widgets(profile, slot)

    # Assert
    guids = [row["guid"] for row in widgets]
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
    assert set(layout["hubs"]) == set(MANAGED)
    assert ApplyHubLayout().name == "apply_hub_layout"


@pytest.mark.parametrize("slot", MANAGED)
def test_every_label_fits_the_row_strip(profile: Path, slot: str) -> None:
    """The strip cuts at about 15 characters at 1080p; "Continue Watching" showed as "Continue Watchi…"."""
    # Act
    labels = [row["label"] for row in _widgets(profile, slot)]

    # Assert
    assert [label for label in labels if len(label) > 15] == []


# --- rows -------------------------------------------------------------------


def test_discover_rows_carry_their_params(profile: Path) -> None:
    # Act
    comedy = next(row for row in _menu(profile, "1101", "Genres") if row["label"] == "Comedy")

    # Assert
    assert _params(comedy) == {
        "info": "discover",
        "with_id": "True",
        "tmdb_type": "movie",
        "with_genres": "35",
        "sort_by": "popularity.desc",
        "vote_count.gte": "300",
        "widget": "True",
    }


@pytest.mark.parametrize(
    ("slot", "label", "expected"),
    [
        ("1101", "Popular", {"info": "popular", "tmdb_type": "movie", "widget": "True"}),
        ("1101", "Coming Soon", {"info": "upcoming", "tmdb_type": "movie", "widget": "True"}),
        ("1104", "Trending Movies", {"info": "trending_week", "tmdb_type": "movie", "widget": "True"}),
    ],
)
def test_a_named_tmdb_list_becomes_its_own_route(profile: Path, slot: str, label: str, expected: dict[str, str]) -> None:
    """Not every list is a discover query; `with_id` belongs to discover alone."""
    # Act
    row = _row(_widgets(profile, slot), label)

    # Assert
    assert _params(row) == expected


def test_a_row_style_is_carried_and_an_unset_one_is_left_to_the_skin(profile: Path) -> None:
    # Act
    home = _widgets(profile, "home")

    # Assert
    assert _row(home, "Continue")["widget_style"] == "Landscape"
    assert _row(home, "Added Movies")["widget_style"] == "Poster"
    assert "widget_style" not in _menu(profile, "1101", "Genres")[0]


def test_library_rows_lead_so_the_screen_paints_before_any_tmdb_call(profile: Path) -> None:
    # Act
    movies = _widgets(profile, "1101")
    home = _widgets(profile, "home")

    # Assert
    assert movies[0]["path"].startswith("library://")
    assert movies[1]["path"].startswith("library://")
    assert all(not row["path"].startswith("plugin://plugin.video.themoviedb.helper") for row in home[:4])


def test_home_continues_movies_and_episodes_in_one_row(profile: Path) -> None:
    """A Kodi smartlist holds one media type, so the old row was TV only and half-watched movies never surfaced."""
    # Act
    row = _row(_widgets(profile, "home"), "Continue")

    # Assert
    assert row["path"].startswith("plugin://script.embuary.helper/")
    assert _params(row) == {"info": "getinprogress", "type": "mixed"}


def test_next_up_is_the_same_list_on_home_and_series(profile: Path) -> None:
    # Act
    home = _row(_widgets(profile, "home"), "Next Up")
    series = _row(_widgets(profile, "1102"), "Next Up")

    # Assert
    assert home["path"] == series["path"]
    assert _params(home) == {"info": "getnextup", "type": "tvshow"}


def test_airing_now_excludes_new_series_and_is_identical_on_home_and_series(profile: Path) -> None:
    """`New Series` is series that debuted recently; this row is the other half. `first_air_date.lte` keeps them apart."""
    # Act
    home = _params(_row(_widgets(profile, "home"), "Airing Now"))
    series = _params(_row(_widgets(profile, "1102"), "Airing Now"))

    # Assert
    assert home == series
    assert home["tmdb_type"] == "tv"
    assert home["first_air_date.lte"] == "T-90"
    assert home["air_date.gte"] == "T-0"
    assert home["air_date.lte"] == "T+14"


def test_maddys_row_is_the_series_crime_and_mystery_genre(profile: Path) -> None:
    """A hand copy had dropped documentaries (genre 99); the two now share one filter."""
    # Act
    home = _params(_row(_widgets(profile, "home"), "Maddy's Picks"))
    series = _params(next(row for row in _menu(profile, "1102", "Genres") if row["label"] == "Crime & Mystery"))

    # Assert
    assert home == series
    assert home["with_genres"] == "80|9648|99"


def test_top_rated_filters_at_eight_and_promises_no_percentage(profile: Path) -> None:
    """A 9.0 floor returned an empty row: TMDb's best-rated titles with a real vote count sit near 8.7."""
    # Act
    movies = _group(_read(profile, f"{SKINVARS}/skinvariables-shortcut-1101submenu.json"), "Collections")
    series = _group(_read(profile, f"{SKINVARS}/skinvariables-shortcut-1102submenu.json"), "Collections")
    rows = [row for row in (*movies, *series) if row["label"] == "Top Rated"]

    # Assert
    assert len(rows) == 2
    assert all(_params(row)["vote_average.gte"] == "8.0" for row in rows)
    assert not [row for row in (*movies, *series) if "%" in row["label"]]


@pytest.mark.parametrize(("label", "slot"), [("Top Movies", "1101"), ("Top Shows", "1102")])
def test_discovers_top_rows_reuse_the_collection_queries(profile: Path, label: str, slot: str) -> None:
    """Merge keys relabel a row without copying its filter, so the two cannot drift."""
    # Act
    top = _row(_widgets(profile, "1104"), label)
    collection = next(row for row in _menu(profile, slot, "Collections") if row["label"] == "Top Rated")

    # Assert
    assert top["path"] == collection["path"]
    assert top["widget_style"] == "Poster"


def test_movies_browse_by_service_through_streaming_availability(profile: Path) -> None:
    """TMDb movies have no network filter; `with_networks` on a movie query is ignored and silently means "all popular movies"."""
    # Act
    params = [_params(row) for row in _menu(profile, "1101", "Streaming On")]

    # Assert
    assert params
    assert all(p["tmdb_type"] == "movie" and p["with_watch_providers"] and p["watch_region"] == "US" for p in params)
    assert not [p for p in params if "with_networks" in p]


def test_every_streaming_service_is_browsable_for_both_movies_and_series(profile: Path) -> None:
    """The movie list is the streaming half of the series list; cable networks have no movie catalogue to filter."""
    # Act
    movies = [row["label"] for row in _menu(profile, "1101", "Streaming On")]
    series = [row["label"] for row in _menu(profile, "1102", "Networks")]

    # Assert
    assert movies == ["Netflix", "HBO / Max", "Prime Video", "Apple TV+", "Disney+", "Hulu", "Paramount+", "Peacock"]
    assert series[: len(movies)] == movies
    assert series[len(movies) :] == ["FX", "AMC", "Showtime", "Adult Swim"]


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Movies", {"tmdb_type": "movie", "primary_release_date.gte": "T-365", "primary_release_date.lte": "T-0"}),
        ("New Series", {"tmdb_type": "tv", "first_air_date.gte": "T-365", "first_air_date.lte": "T-0"}),
        ("Returning Series", {"tmdb_type": "tv", "first_air_date.lte": "T-365", "air_date.gte": "T-365", "air_date.lte": "T-0"}),
    ],
)
def test_discover_offers_the_past_twelve_months_as_rolling_windows(profile: Path, label: str, expected: dict[str, str]) -> None:
    """Rolling, because TMDbHelper resolves only day offsets: a calendar year would go stale every January."""
    # Act
    row = next(row for row in _menu(profile, "1104", "Past 12 Months") if row["label"] == label)

    # Assert
    params = _params(row)
    assert {key: params[key] for key in expected} == expected


# --- strip and menu ---------------------------------------------------------


@pytest.mark.parametrize("slot", MANAGED)
def test_the_strip_holds_only_rows_of_titles(profile: Path, slot: str) -> None:
    """A list of lists in the strip (tiles, or a preview that never shows) reads as clutter on the TV; those go in ▶."""
    # Act
    paths = [row["path"] for row in _widgets(profile, slot)]

    # Assert
    assert not [path for path in paths if path in ("Custom_Submenu", "Stacked_Folder")]
    assert not [row for row in _widgets(profile, slot) if row.get("submenu")]


@pytest.mark.parametrize(
    ("slot", "expected"),
    [
        ("1101", ["Genres", "Streaming On", "By Decade", "Collections"]),
        ("1102", ["Genres", "Networks", "International", "By Decade", "Collections"]),
        ("1104", ["Past 12 Months", "Hidden Gems", "International"]),
    ],
)
def test_each_hubs_menu_holds_its_lists_of_lists(profile: Path, slot: str, expected: list[str]) -> None:
    # Act
    submenu = _read(profile, f"{SKINVARS}/skinvariables-shortcut-{slot}submenu.json")

    # Assert
    assert [group["label"] for group in submenu[:-1]] == expected


def test_a_hub_page_opens_a_menu_group_as_a_folder_of_its_rows(profile: Path) -> None:
    # Act
    node = _read(profile, f"{NODES}/movies_hub_main.json")
    genres = next(entry for entry in node["list"] if entry["name"] == "Genres")

    # Assert
    assert _params(genres) == {"info": "dir_custom_node", "filename": "movies_hub_main--genres.json"}
    folder = _read(profile, f"{NODES}/movies_hub_main--genres.json")
    assert [entry["path"] for entry in folder["list"]] == [row["path"] for row in _menu(profile, "1101", "Genres")]


def test_a_hub_page_lists_each_row_once(profile: Path) -> None:
    # Act
    node = _read(profile, f"{NODES}/movies_hub_main.json")
    names = [entry["name"] for entry in node["list"]]

    # Assert
    assert node["name"] == "MOVIES"
    assert names == ["Resume Movies", "Added Movies", "New Releases", "Popular", "Coming Soon", "Genres", "Streaming On", "By Decade", "Collections"]
    assert all(entry["widget"] == "False" for entry in node["list"])


def test_a_hub_page_opens_each_submenu_group_as_a_folder_of_all_its_rows(profile: Path) -> None:
    """The page used to link a group to its first row, so "Genres" opened Action & Adventure."""
    # Act
    node = _read(profile, f"{NODES}/movies_hub_main.json")
    decades = next(entry for entry in node["list"] if entry["name"] == "By Decade")

    # Assert
    folder = _read(profile, f"{NODES}/{_params(decades)['filename']}")
    assert [entry["name"] for entry in folder["list"]] == ["2020s", "2010s", "2000s", "1990s", "Before 1990"]


def test_every_folder_link_on_every_hub_page_resolves(profile: Path) -> None:
    # Assert
    for spec in load_layout()["hubs"].values():
        node = _read(profile, f"{NODES}/{spec['node']}")
        for entry in node["list"]:
            if "dir_custom_node" in entry["path"]:
                assert (profile / NODES / _params(entry)["filename"]).is_file(), entry["name"]


def test_group_nodes_from_a_previous_build_are_removed(tmp_path: Path) -> None:
    """A renamed group would otherwise linger in TMDbHelper's node list."""
    # Arrange
    (tmp_path / NODES).mkdir(parents=True)
    (tmp_path / NODES / "movies_hub_main--old-group.json").write_text("{}", encoding="utf-8")
    (tmp_path / NODES / "someone_elses_node.json").write_text("{}", encoding="utf-8")

    # Act
    ApplyHubLayout().apply(tmp_path, {})

    # Assert
    assert not (tmp_path / NODES / "movies_hub_main--old-group.json").exists()
    assert (tmp_path / NODES / "someone_elses_node.json").exists()


def test_two_groups_that_would_share_a_node_file_are_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two groups whose labels slug alike would overwrite each other's folder."""
    # Arrange
    row = {"label": "Picks", "discover": {"tmdb_type": "movie"}}
    layout = {
        "hubs": {
            "1101": {"node": "m.json", "node_name": "M", "widgets": [], "submenu": [{"label": "Picks", "rows": [row]}, {"label": "PICKS!", "rows": [row]}]}
        }
    }
    monkeypatch.setattr("fleetctl.apps.kodi.transforms.hub_layout.load_layout", lambda name: layout)

    # Act / Assert
    with pytest.raises(FleetError, match="picks"):
        ApplyHubLayout().apply(tmp_path, {})


def test_series_shows_what_airs_next_without_trakt(profile: Path) -> None:
    """The skin's Next Aired calendar is Trakt's calendar under the hood and showed a 401; this route asks TMDb."""
    # Act
    row = _row(_widgets(profile, "1102"), "Coming Up")

    # Assert
    assert _params(row) == {"info": "library_airingnext", "tmdb_type": "tv", "widget": "True"}
    assert not [r for slot in MANAGED for r in _widgets(profile, slot) if "trakt" in r["path"] or "nextaired" in r["path"]]
