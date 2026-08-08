"""Which recipe a build uses, decided at the composition root.

The decision needs the artifact store, the inventory and the device pack at
once, so neither `apps/kodi` nor `packs/steamdeck` can make it alone. These
tests pin the resolution order and the fallbacks around it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, cast

import pytest

from fleetctl.apps.kodi.pack import KodiApp
from fleetctl.cli.bootstrap import Container
from fleetctl.cli.main import _app_profile, _transforms_for
from fleetctl.core.artifacts.ref import ArtifactRef
from fleetctl.core.artifacts.store import LocalArtifactStore
from fleetctl.core.effects import Capability
from fleetctl.core.inventory.device import Device
from fleetctl.core.inventory.store import DeviceStore
from fleetctl.core.registry import RegisteredStep, Registry
from fleetctl.core.transport.base import CommandRunner


class _DeckLikePack:
    """A pack whose hardware needs a recipe other than the app's default."""

    id = "decklike"
    platform = "linux"
    capabilities = frozenset({Capability.EXEC})
    probe_priority = 20
    app_profiles = {"kodi": "deck"}

    def probe(self, runner: CommandRunner) -> dict[str, str] | None:
        return None

    def steps(self) -> Iterable[RegisteredStep]:
        return []


class _PlainPack(_DeckLikePack):
    """A pack that is content with whatever each app ships as its default."""

    id = "plain"
    app_profiles: dict[str, str] = {}


@pytest.fixture
def registry() -> Registry:
    populated = Registry()
    populated.register_device_pack(cast(Any, _DeckLikePack()))
    populated.register_device_pack(cast(Any, _PlainPack()))
    populated.register_app_pack(KodiApp())
    return populated


@pytest.fixture
def container(tmp_path: Path, registry: Registry) -> Container:
    """A container carrying only what profile resolution reads."""
    store = LocalArtifactStore(tmp_path / "store")
    inventory = DeviceStore(tmp_path / "devices.yml")
    inventory.save(
        [
            Device(id="deck-1", type="decklike", address="192.168.1.50"),
            Device(id="stick-1", type="plain", address="192.168.1.51"),
            Device(id="odd-1", type="plain", address="192.168.1.52", vars={"kodi": {"profile": "deck"}}),
        ]
    )

    class _Fake:
        pass

    fake = _Fake()
    fake.registry = registry  # type: ignore[attr-defined]
    fake.artifacts = store  # type: ignore[attr-defined]
    fake.inventory = inventory  # type: ignore[attr-defined]
    return cast(Container, fake)


def _publish_capture(container: Container, tmp_path: Path, name: str, device_id: str) -> str:
    """RETURNS: str: The wire ref of a published capture attributed to `device_id`."""
    local = tmp_path / name
    local.write_bytes(b"archive")
    ref = ArtifactRef(kind="captures", name=name)
    container.artifacts.put(local, ref, meta={"app": "kodi", "device_id": device_id})
    return ref.wire


def test_a_decks_capture_builds_with_the_decks_recipe(container: Container, tmp_path: Path) -> None:
    """The failure this prevents: a panel build of a Deck capture that silently
    used `gold`, producing an image with ARM binaries the Deck cannot run."""
    # Arrange
    source = _publish_capture(container, tmp_path, "deck-1_1.tar.gz", "deck-1")
    flags: dict[str, Any] = {"source": source}

    # Act
    chain = _transforms_for(container, "kodi", flags)

    # Assert
    assert chain == KodiApp("deck").transforms
    assert flags["profile"] == "deck"


def test_a_sticks_capture_builds_with_the_default_recipe(container: Container, tmp_path: Path) -> None:
    # Arrange
    source = _publish_capture(container, tmp_path, "stick-1_1.tar.gz", "stick-1")
    flags: dict[str, Any] = {"source": source}

    # Act
    chain = _transforms_for(container, "kodi", flags)

    # Assert
    assert chain == KodiApp("gold").transforms
    assert flags["profile"] == "gold"


def test_an_explicit_profile_beats_the_captures_device(container: Container, tmp_path: Path) -> None:
    """An operator naming a profile has a reason; resolution must not override it."""
    # Arrange
    source = _publish_capture(container, tmp_path, "deck-1_2.tar.gz", "deck-1")
    flags: dict[str, Any] = {"source": source, "profile": "gold"}

    # Act
    chain = _transforms_for(container, "kodi", flags)

    # Assert
    assert chain == KodiApp("gold").transforms


def test_device_vars_beat_the_packs_default(container: Container) -> None:
    """One odd device is a config edit, not a code change."""
    # Arrange
    device = container.inventory.get("odd-1")
    assert device is not None

    # Act / Assert
    assert _app_profile(container, "kodi", device) == "deck"


def test_a_capture_with_no_recorded_device_falls_back_to_the_default(container: Container, tmp_path: Path) -> None:
    """Captures published before device attribution must still build."""
    # Arrange
    local = tmp_path / "orphan.tar.gz"
    local.write_bytes(b"archive")
    container.artifacts.put(local, ArtifactRef(kind="captures", name="orphan.tar.gz"), meta={"app": "kodi"})
    flags: dict[str, Any] = {"source": "captures/orphan.tar.gz"}

    # Act
    chain = _transforms_for(container, "kodi", flags)

    # Assert
    assert chain == KodiApp("gold").transforms


def test_a_device_whose_pack_is_not_installed_still_names_a_profile(container: Container, tmp_path: Path) -> None:
    """A device typed for a pack this install lacks must not break the build,
    and must not resolve to "no opinion" either -- a device with no profile
    can be sent a build shaped for other hardware, because nothing disagrees."""
    # Arrange
    container.inventory.save([Device(id="ghost-1", type="absent", address="192.168.1.53")])
    device = container.inventory.get("ghost-1")
    assert device is not None

    # Act / Assert
    assert _app_profile(container, "kodi", device) == KodiApp().profile


def test_a_pack_step_resolves_no_profile(container: Container) -> None:
    """`steamdeck.maintain` is not an app step; nothing there has a profile."""
    # Arrange
    device = container.inventory.get("deck-1")
    assert device is not None

    # Act / Assert
    assert _app_profile(container, "steamdeck", device) == ""
