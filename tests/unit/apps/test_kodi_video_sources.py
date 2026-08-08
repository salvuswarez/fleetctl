"""Merging video sources into a captured sources.xml."""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

from fleetctl.apps.kodi.pack import KodiApp
from fleetctl.apps.kodi.transforms.sources import AddVideoSources
from fleetctl.core.errors import FleetError

# Shaped like a captured file: a fleet share already present under <video>.
CAPTURED = """<?xml version="1.0" encoding="utf-8"?>
<sources>
    <video>
        <default pathversion="1"></default>
        <source>
            <name>NAS Movies</name>
            <path pathversion="1">smb://example/Movies/</path>
            <allowsharing>true</allowsharing>
        </source>
    </video>
    <files>
        <default pathversion="1"></default>
    </files>
</sources>
"""

DECK_MOVIES = {"name": "Deck Downloads - Movies", "path": "/run/media/deck/SC400/kodi/Movies/", "thumbnail": "DefaultMovies.png"}


@pytest.fixture
def profile(tmp_path: Path) -> Path:
    """RETURNS: Path: An extracted profile holding a captured sources.xml."""
    userdata = tmp_path / "userdata"
    userdata.mkdir(parents=True)
    (userdata / "sources.xml").write_text(CAPTURED, encoding="utf-8")
    return tmp_path


def _video_sources(profile: Path) -> dict[str, str]:
    """RETURNS: dict[str, str]: Name to path for every source under `<video>`."""
    root = ElementTree.parse(profile / "userdata" / "sources.xml").getroot()
    video = root.find("video")
    assert video is not None
    return {source.findtext("name") or "": (source.findtext("path") or "").strip() for source in video.findall("source")}


def test_a_source_is_added_alongside_the_captured_ones(profile: Path) -> None:
    """The fleet's own shares must survive; this merges rather than replaces."""
    # Act
    changes = AddVideoSources(sources=(DECK_MOVIES,)).apply(profile, {})

    # Assert
    found = _video_sources(profile)
    assert found["NAS Movies"] == "smb://example/Movies/"
    assert found["Deck Downloads - Movies"] == DECK_MOVIES["path"]
    assert len(changes) == 1


def test_applying_twice_does_not_duplicate(profile: Path) -> None:
    """A rebuild must not accumulate the same source."""
    # Act
    AddVideoSources(sources=(DECK_MOVIES,)).apply(profile, {})
    second = AddVideoSources(sources=(DECK_MOVIES,)).apply(profile, {})

    # Assert
    assert second == []
    assert len(_video_sources(profile)) == 2


def test_the_thumbnail_is_written_when_given(profile: Path) -> None:
    # Act
    AddVideoSources(sources=(DECK_MOVIES,)).apply(profile, {})

    # Assert
    root = ElementTree.parse(profile / "userdata" / "sources.xml").getroot()
    added = [s for s in root.find("video").findall("source") if s.findtext("name") == DECK_MOVIES["name"]][0]  # type: ignore[union-attr]
    assert added.findtext("thumbnail") == "DefaultMovies.png"


def test_an_entry_missing_a_path_fails_the_build(profile: Path) -> None:
    """A half-written source would be silently useless on the device."""
    # Act / Assert
    with pytest.raises(FleetError, match="needs both name and path"):
        AddVideoSources(sources=({"name": "Broken"},)).apply(profile, {})


def test_a_profile_without_sources_is_not_an_error(tmp_path: Path) -> None:
    # Act / Assert
    assert AddVideoSources(sources=(DECK_MOVIES,)).apply(tmp_path, {}) == []


def test_unparseable_sources_do_not_fail_the_build(tmp_path: Path) -> None:
    # Arrange
    userdata = tmp_path / "userdata"
    userdata.mkdir(parents=True)
    (userdata / "sources.xml").write_text("<sources><video>", encoding="utf-8")

    # Act / Assert
    assert AddVideoSources(sources=(DECK_MOVIES,)).apply(tmp_path, {}) == []


def test_nothing_configured_is_a_clean_no_op(profile: Path) -> None:
    # Act / Assert
    assert AddVideoSources().apply(profile, {}) == []


def test_the_deck_profile_adds_both_download_folders() -> None:
    # Act
    chain = {transform.name: transform for transform in KodiApp("deck").transforms}

    # Assert
    assert "add_video_sources" in chain
    paths = {entry["path"] for entry in chain["add_video_sources"].sources}  # type: ignore[attr-defined]
    assert paths == {"/run/media/deck/SC400/kodi/Movies/", "/run/media/deck/SC400/kodi/TVShows/"}


def test_the_gold_profile_adds_none() -> None:
    """A Fire Stick has no SD card; the transform is only added on request."""
    # Act / Assert
    assert "add_video_sources" not in [transform.name for transform in KodiApp("gold").transforms]
