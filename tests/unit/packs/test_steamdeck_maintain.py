"""The Steam Deck's maintenance step, and the fleet coverage it closes."""

from __future__ import annotations

from typing import Any

import pytest

from fleetctl.core.effects import Effect
from fleetctl.core.registry import discover
from fleetctl.core.transport.fake import FakeTransport
from fleetctl.packs.steamdeck.pack import MAINTAIN, SteamDeckPack

STAGING = "~/.cache/fleetctl"


def _transport(free: int = 8 * 1024**3) -> FakeTransport:
    transport = FakeTransport(responses={"echo $HOME": "/home/deck"})
    transport.free_space = free
    return transport


def test_maintain_is_declared_destructive() -> None:
    """It deletes. A mislabelled destructive step bypasses approval."""
    # Act / Assert
    assert MAINTAIN.effect is Effect.DESTRUCTIVE


def test_maintain_prunes_the_staging_directory(device_context: Any) -> None:
    """The `~` must be expanded before the path is quoted. Quoted, the remote
    shell leaves it literal, so `rm -rf` targets a `~` directory that does not
    exist — it succeeds and deletes nothing. Caught on hardware, not here."""
    # Arrange
    transport = _transport()
    context = device_context(transport, device_type="steamdeck")

    # Act
    result = SteamDeckPack().maintain(context)

    # Assert
    assert result.facts["pruned"] == [STAGING]
    assert "rm -rf /home/deck/.cache/fleetctl" in transport.commands()
    assert not [command for command in transport.commands() if "~" in command]


def test_maintain_trims_the_journal(device_context: Any) -> None:
    """systemd's journal is uncapped and grows without bound on a device that
    is rarely rebooted."""
    # Arrange
    transport = _transport()

    # Act
    SteamDeckPack().maintain(device_context(transport, device_type="steamdeck"))

    # Assert
    assert any("journalctl --user --vacuum-time=7d" in command for command in transport.commands())


def test_unused_runtimes_are_left_alone_by_default(device_context: Any) -> None:
    """Removal is slow and can surprise someone mid-session, so it is opt-in."""
    # Arrange
    transport = _transport()

    # Act
    result = SteamDeckPack().maintain(device_context(transport, device_type="steamdeck"))

    # Assert
    assert result.facts["runtimes_removed"] is False
    assert not [command for command in transport.commands() if "flatpak uninstall" in command]


def test_runtimes_are_removed_when_the_recipe_asks(device_context: Any) -> None:
    # Arrange
    transport = _transport()
    recipe = {"prune_paths": [], "journal_retention": "", "remove_unused_runtimes": True}
    context = device_context(transport, device_type="steamdeck", config={"maintenance": recipe})

    # Act
    result = SteamDeckPack().maintain(context)

    # Assert
    assert result.facts["runtimes_removed"] is True
    assert any("flatpak uninstall --unused" in command for command in transport.commands())


def test_maintain_reports_what_it_reclaimed(device_context: Any) -> None:
    # Arrange
    transport = _transport()
    context = device_context(transport, device_type="steamdeck")

    # Act
    result = SteamDeckPack().maintain(context)

    # Assert
    assert "reclaimed_bytes" in result.facts
    assert result.facts["free_bytes"] == transport.free_space


def test_maintain_touches_nothing_application_specific(device_context: Any) -> None:
    """A device pack must not know which applications are installed. Kodi
    profile work belongs to the app pack."""
    # Arrange
    transport = _transport()

    # Act
    SteamDeckPack().maintain(device_context(transport, device_type="steamdeck"))

    # Assert
    forbidden = ("kodi", "xbmc", ".var/app", "addons", "userdata")
    assert not [command for command in transport.commands() if any(term in command.lower() for term in forbidden)]


@pytest.mark.parametrize("step_id", ["steamdeck.check", "steamdeck.maintain"])
def test_the_panel_facing_steps_are_registered(step_id: str) -> None:
    """The HA panel's per-device buttons resolve a step by id; a missing one
    is a button that silently does nothing."""
    # Act
    registered = {step.spec.id for step in SteamDeckPack().steps()}

    # Assert
    assert step_id in registered


def test_every_managed_device_type_has_a_maintain_step() -> None:
    """`maintain_all` fans out per type; a type without one is skipped in
    silence."""
    # Arrange
    registry = discover()
    steps = {step.spec.id for step in registry.steps()}

    # Act
    # `linux_host` is a presence-and-facts pack with no vendor cleanup of its
    # own; every type fleetctl actually manages needs one.
    managed = {pack.id for pack in registry.device_packs()} - {"linux_host"}

    # Assert
    missing = sorted(name for name in managed if f"{name}.maintain" not in steps)
    assert missing == [], f"device types with no maintain step: {missing}"
