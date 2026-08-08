"""How a transport gets its credentials, for a scan and for a known device."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fleetctl.cli.bootstrap import Container
from fleetctl.core.artifacts.store import LocalArtifactStore
from fleetctl.core.inventory.device import Device
from fleetctl.core.inventory.store import DeviceStore
from fleetctl.core.observability.audit import ChainedAuditWriter, InMemoryAuditSink
from fleetctl.core.operations.registry import OperationRegistry
from fleetctl.core.registry import Registry

FLEET_SSH = {"user": "deck", "key_path": "/keys/id_ed25519", "known_hosts": "/keys/known_hosts"}


@pytest.fixture
def container(tmp_path: Path) -> Any:
    """RETURNS: Container: A container with fleet-level SSH defaults configured."""

    def _build(config: dict[str, Any] | None = None) -> Container:
        return Container(
            registry=Registry(),
            inventory=DeviceStore(tmp_path / "devices.yml"),
            artifacts=LocalArtifactStore(tmp_path / "store"),
            operations=OperationRegistry(),
            audit=ChainedAuditWriter(InMemoryAuditSink()),
            config=config if config is not None else {"ssh": dict(FLEET_SSH)},
            home=tmp_path / "home",
            actor="test",
            config_dir=tmp_path / "config",
        )

    return _build


def test_a_scan_gets_the_fleet_ssh_identity(container: Any) -> None:
    """A scan probes hosts that are not in the inventory yet, so there is no
    device record to read a credential from. Without a fleet-level identity an
    SSH probe has no credentials at all and every host fails to authenticate."""
    # Act
    settings = container().transport_settings()

    # Assert
    assert settings["user"] == "deck"
    assert settings["key_path"] == "/keys/id_ed25519"


def test_adb_key_material_is_still_supplied(container: Any) -> None:
    """The Android packs read `key_dir`; adding SSH must not displace it."""
    # Act
    settings = container().transport_settings()

    # Assert
    assert settings["key_dir"].name == "keys"
    assert "audit" in settings


def test_a_device_overrides_the_fleet_identity(container: Any) -> None:
    """One host with a different login must not require changing the fleet's."""
    # Arrange
    device = Device(id="deck-1", type="steamdeck", address="192.168.1.50", vars={"ssh": {"user": "someone-else", "port": 2222}})

    # Act
    settings = container().transport_settings(device)

    # Assert
    assert settings["user"] == "someone-else"
    assert settings["port"] == 2222
    # Untouched keys still come from the fleet defaults.
    assert settings["key_path"] == "/keys/id_ed25519"


def test_a_device_without_ssh_vars_keeps_the_fleet_identity(container: Any) -> None:
    # Arrange
    device = Device(id="deck-1", type="steamdeck", address="192.168.1.50")

    # Act
    settings = container().transport_settings(device)

    # Assert
    assert settings["user"] == "deck"


def test_no_fleet_ssh_config_is_not_an_error(container: Any) -> None:
    """An ADB-only fleet configures no SSH block at all."""
    # Act
    settings = container(config={}).transport_settings()

    # Assert
    assert "user" not in settings
    assert "key_dir" in settings


def test_the_fleet_config_is_not_mutated_by_a_device_override(container: Any) -> None:
    """The container is long-lived; one device's login must not leak into the
    next device's settings."""
    # Arrange
    built = container()
    device = Device(id="deck-1", type="steamdeck", address="192.168.1.50", vars={"ssh": {"user": "someone-else"}})

    # Act
    built.transport_settings(device)
    after = built.transport_settings()

    # Assert
    assert after["user"] == "deck"
    assert built.config["ssh"] == FLEET_SSH
