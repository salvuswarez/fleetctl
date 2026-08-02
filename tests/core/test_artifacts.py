"""Tests for artifact references and the local store."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from fleetctl.core.artifacts.ref import ArtifactRef, sanitize
from fleetctl.core.artifacts.store import ArtifactStore, LocalArtifactStore, require_kind
from fleetctl.core.errors import ArtifactError


@pytest.fixture
def store(tmp_path: Path) -> LocalArtifactStore:
    return LocalArtifactStore(tmp_path / "store")


@pytest.fixture
def payload(tmp_path: Path) -> Path:
    path = tmp_path / "build.tar.gz"
    path.write_bytes(b"z" * 256)
    return path


def test_local_store_satisfies_the_protocol(store: LocalArtifactStore) -> None:
    assert isinstance(store, ArtifactStore)


@pytest.mark.parametrize("wire", ["../etc/passwd", "builds/../secret", "builds", "a/b/c", "builds/", "/builds/x"])
def test_unsafe_references_are_rejected(wire: str) -> None:
    # Act / Assert
    with pytest.raises(ArtifactError):
        ArtifactRef.parse(wire)


def test_a_dotted_capture_name_is_allowed() -> None:
    """Captures mirror an on-device dotted directory name, so a leading dot
    must survive while `..` must not."""
    # Act
    ref = ArtifactRef.parse("captures/.kodi_20260801_101500.tar.gz")

    # Assert
    assert ref.name == ".kodi_20260801_101500.tar.gz"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("build_20260801.tar.gz", "build_20260801.meta.json"),
        (".kodi_20260801.tgz", ".kodi_20260801.meta.json"),
        ("kodi-latest.apk", "kodi-latest.meta.json"),
    ],
)
def test_sidecar_name_is_derived_from_the_artifact_name(name: str, expected: str) -> None:
    assert ArtifactRef(kind="builds", name=name).meta_name == expected


def test_local_path_uses_only_the_basename(tmp_path: Path) -> None:
    """`kind` is a store-side namespace. Joining it into a local path
    produced an unreachable nested path in the predecessor."""
    # Act
    actual = ArtifactRef(kind="builds", name="b.tar.gz").local_path(tmp_path)

    # Assert
    assert actual == tmp_path / "b.tar.gz"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Living Room Stick", "living_room_stick"), ("../../etc", "etc"), ("", "unknown"), ("...", "unknown")],
)
def test_sanitize_reduces_untrusted_names(raw: str, expected: str) -> None:
    assert sanitize(raw) == expected


def test_put_then_get_round_trips(store: LocalArtifactStore, payload: Path, tmp_path: Path) -> None:
    # Arrange
    ref = ArtifactRef(kind="builds", name="build_1.tar.gz")

    # Act
    info = store.put(payload, ref, meta={"profile": "gold"})
    restored = store.get(ref, tmp_path / "out" / "build_1.tar.gz")

    # Assert
    assert info.size == 256
    assert info.meta["profile"] == "gold"
    assert restored.read_bytes() == b"z" * 256


def test_getting_a_missing_artifact_raises(store: LocalArtifactStore, tmp_path: Path) -> None:
    with pytest.raises(ArtifactError):
        store.get(ArtifactRef(kind="builds", name="nope.tar.gz"), tmp_path / "x")


def test_storing_a_missing_file_raises(store: LocalArtifactStore, tmp_path: Path) -> None:
    with pytest.raises(ArtifactError):
        store.put(tmp_path / "absent.tar.gz", ArtifactRef(kind="builds", name="b.tar.gz"))


def test_latest_returns_the_newest_artifact(store: LocalArtifactStore, payload: Path) -> None:
    # Arrange
    for name in ("build_1.tar.gz", "build_2.tar.gz", "build_3.tar.gz"):
        store.put(payload, ArtifactRef(kind="builds", name=name))
        time.sleep(0.01)

    # Act
    actual = store.latest("builds")

    # Assert
    assert actual.name == "build_3.tar.gz"


def test_latest_on_an_empty_kind_raises(store: LocalArtifactStore) -> None:
    with pytest.raises(ArtifactError):
        store.latest("builds")


def test_listing_an_absent_kind_is_empty_not_an_error(store: LocalArtifactStore) -> None:
    assert store.list("builds") == []


def test_sidecars_are_excluded_from_listings(store: LocalArtifactStore, payload: Path) -> None:
    # Arrange
    store.put(payload, ArtifactRef(kind="builds", name="build_1.tar.gz"))

    # Act
    listed = store.list("builds")

    # Assert
    assert [info.ref.name for info in listed] == ["build_1.tar.gz"]


def test_an_unreadable_sidecar_does_not_drop_the_artifact(store: LocalArtifactStore, payload: Path, tmp_path: Path) -> None:
    """The predecessor swallowed sidecar failures wholesale, so a transient
    error made backups silently vanish from the picker."""
    # Arrange
    ref = ArtifactRef(kind="builds", name="build_1.tar.gz")
    store.put(payload, ref)
    (tmp_path / "store" / "builds" / "build_1.meta.json").write_text("{not json", encoding="utf-8")

    # Act
    listed = store.list("builds")

    # Assert
    assert [info.ref.name for info in listed] == ["build_1.tar.gz"]
    assert listed[0].meta == {}


def test_require_kind_rejects_a_reference_from_another_namespace() -> None:
    """Deploy ships built profiles, never raw captures."""
    # Act / Assert
    with pytest.raises(ArtifactError):
        require_kind(ArtifactRef(kind="captures", name="c.tar.gz"), "builds")


def test_require_kind_passes_a_matching_reference_through() -> None:
    # Arrange
    ref = ArtifactRef(kind="builds", name="b.tar.gz")

    # Act / Assert
    assert require_kind(ref, "builds") is ref


def test_delete_removes_artifact_and_sidecar(store: LocalArtifactStore, payload: Path) -> None:
    # Arrange
    ref = ArtifactRef(kind="builds", name="build_1.tar.gz")
    store.put(payload, ref)

    # Act
    store.delete(ref)
    store.delete(ref)  # absent is not an error

    # Assert
    assert store.exists(ref) is False
    assert store.list("builds") == []
