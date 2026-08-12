"""Starting Kodi without the app pack knowing what a launcher activity is."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fleetctl.apps.kodi import launch
from fleetctl.core.effects import Capability, Effect
from fleetctl.core.errors import FleetError, TransportError
from fleetctl.core.transport.fake import FakeTransport
from fleetctl.packs.android.appmgr import AndroidAppManager
from fleetctl.packs.posix.appmgr import FlatpakAppManager

PACKAGE = "org.xbmc.kodi"
RESOLVE_LEANBACK = f"cmd package resolve-activity --brief -c android.intent.category.LEANBACK_LAUNCHER -a android.intent.action.MAIN {PACKAGE}"
RESOLVE_LAUNCHER = f"cmd package resolve-activity --brief -c android.intent.category.LAUNCHER -a android.intent.action.MAIN {PACKAGE}"
RESOLVED = f"priority=0 preferredOrder=0 match=0x108000\n{PACKAGE}/.Splash"


def _running() -> dict[str, str]:
    return {
        RESOLVE_LEANBACK: RESOLVED,
        f"am start -n {PACKAGE}/.Splash": "Starting: Intent",
        f"pidof {PACKAGE}": "11191",
    }


def test_launch_resolves_the_activity_and_starts_it(device_context: Any) -> None:
    """The step names no activity: the pack asks the platform what to start."""
    # Arrange
    transport = FakeTransport(responses=_running())
    context = device_context(transport, device_type="shield")

    # Act
    result = launch.launch(context)

    # Assert
    assert result.facts["launched"] is True
    assert f"am start -n {PACKAGE}/.Splash" in transport.commands()


def test_launch_falls_back_to_the_phone_launcher_category(device_context: Any) -> None:
    """A device with no leanback entry still has a launchable activity."""
    # Arrange
    responses = {RESOLVE_LEANBACK: "", RESOLVE_LAUNCHER: RESOLVED, f"am start -n {PACKAGE}/.Splash": "", f"pidof {PACKAGE}": "11191"}
    transport = FakeTransport(responses=responses)
    context = device_context(transport, device_type="shield")

    # Act
    result = launch.launch(context)

    # Assert
    assert result.facts["launched"] is True


def test_launch_fails_when_the_package_exposes_no_launchable_activity(device_context: Any) -> None:
    """Better than starting nothing and reporting success."""
    # Arrange
    context = device_context(FakeTransport(), device_type="shield")

    # Act / Assert
    with pytest.raises(TransportError, match="no launchable activity"):
        launch.launch(context)


def test_launch_fails_when_nothing_is_running_afterwards(device_context: Any) -> None:
    """`am start` writes failure to stdout and the transport cannot read an
    exit status, so the process list is the only evidence available."""
    # Arrange
    responses = {RESOLVE_LEANBACK: RESOLVED, f"am start -n {PACKAGE}/.Splash": "Error: Activity not started", f"pidof {PACKAGE}": ""}
    transport = FakeTransport(responses=responses)
    context = device_context(transport, device_type="shield")

    # Act / Assert
    with pytest.raises(TransportError, match="no process afterwards"):
        launch.launch(context)


def test_launching_an_already_running_app_is_not_an_error(device_context: Any) -> None:
    """The trigger for this step cannot know whether Kodi is already up, so
    launching twice has to be safe."""
    # Arrange
    transport = FakeTransport(responses=_running())
    context = device_context(transport, device_type="shield")

    # Act
    first = launch.launch(context)
    second = launch.launch(context)

    # Assert
    assert first.facts["launched"] is second.facts["launched"] is True


def test_the_step_is_mutating_not_destructive() -> None:
    """It starts a process and changes what is on screen; it destroys nothing.
    Declaring it destructive would demand approval for every trigger."""
    # Act / Assert
    assert launch.LAUNCH.effect is Effect.MUTATING
    assert launch.LAUNCH.requires == frozenset({Capability.EXEC, Capability.APPS})


def test_a_flatpak_host_refuses_rather_than_starting_a_doomed_process() -> None:
    """`flatpak run` over SSH has no session bus or display. Starting a process
    that dies immediately would report success for a black screen."""
    # Arrange
    manager = FlatpakAppManager(FakeTransport())

    # Act / Assert
    with pytest.raises(FleetError, match="not supported"):
        manager.launch("tv.kodi.Kodi")


def test_the_android_manager_still_satisfies_the_app_manager_protocol(tmp_path: Path) -> None:
    """Adding a verb to the protocol must not leave an adapter behind."""
    # Arrange
    from fleetctl.core.appmgr import AppManager

    # Act / Assert
    assert isinstance(AndroidAppManager(FakeTransport()), AppManager)
    assert isinstance(FlatpakAppManager(FakeTransport()), AppManager)
