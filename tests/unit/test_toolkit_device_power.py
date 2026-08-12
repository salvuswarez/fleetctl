"""The cheap power read a poller uses to decide when a device woke up.

Deliberately not a step. A polled read routed through `run_step` becomes an
uncancellable RUNNING operation per poll — this project has made that mistake
once already, so the absence of an operation record is asserted as firmly as
the reading itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import pytest

from fleetctl.agent.toolkit import Toolkit
from fleetctl.cli.bootstrap import build_container
from fleetctl.core.effects import Capability
from fleetctl.core.errors import TransportError
from fleetctl.core.inventory.device import Device
from fleetctl.core.registry import RegisteredStep, Registry
from fleetctl.core.transport.base import CommandRunner, Transport
from fleetctl.core.transport.fake import FakeTransport
from fleetctl.packs.android import actions

WAKEFULNESS = "dumpsys power | grep mWakefulness="
AWAKE = {WAKEFULNESS: "  mWakefulness=Awake\n  mWakefulnessChanging=false"}
ASLEEP = {WAKEFULNESS: "  mWakefulness=Asleep"}

DEVICES = "devices:\n  - id: stub-1\n    type: stub\n    address: 192.168.1.50\n"


class _PowerPack:
    """A pack that answers for power, and records every transport it opened."""

    id = "stub"
    platform = "stub"
    capabilities = frozenset({Capability.EXEC, Capability.POWER})
    probe_priority = 5
    app_profiles: dict[str, str] = {}

    def __init__(self, responses: dict[str, str], *, connect_fails: bool = False) -> None:
        self._responses = responses
        self._connect_fails = connect_fails
        self.opened: list[FakeTransport] = []

    def probe(self, runner: CommandRunner) -> dict[str, str] | None:
        return None

    def transport_for(self, device: Device, settings: Any) -> Transport:
        if self._connect_fails:
            raise TransportError("device is off", target=device.address)
        transport = FakeTransport(target=device.address, responses=self._responses, supported=self.capabilities)
        self.opened.append(transport)
        return transport

    def power_state(self, transport: Transport) -> str:
        return actions.power_state(transport)

    def steps(self) -> Iterable[RegisteredStep]:
        return []


def _toolkit(tmp_path: Path, responses: dict[str, str], *, connect_fails: bool = False) -> tuple[Toolkit, _PowerPack]:
    (tmp_path / "config" / "inventory").mkdir(parents=True)
    (tmp_path / "config" / "fleet.yml").write_text("{}\n", encoding="utf-8")
    (tmp_path / "config" / "inventory" / "devices.yml").write_text(DEVICES, encoding="utf-8")

    pack = _PowerPack(responses, connect_fails=connect_fails)
    registry = Registry()
    registry.register_device_pack(pack)
    container = build_container(config_dir=tmp_path / "config", home=tmp_path / "home", actor="ha:test", registry=registry)
    return Toolkit(container=container, actor="ha:test"), pack


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("  mWakefulness=Awake", "awake"),
        ("  mWakefulness=Asleep", "asleep"),
        ("  mWakefulness=Dozing", "dozing"),
        ("  mWakefulness=Dreaming", "dreaming"),
        ("", ""),
    ],
)
def test_power_state_reads_the_wakefulness(output: str, expected: str) -> None:
    # Arrange
    transport = FakeTransport(responses={WAKEFULNESS: output})

    # Act / Assert
    assert actions.power_state(transport) == expected


def test_power_state_ignores_the_changing_flag_on_the_next_line() -> None:
    """`mWakefulnessChanging=false` also matches the grep, and taking it would
    report a boolean as a power state."""
    # Arrange
    transport = FakeTransport(responses=AWAKE)

    # Act / Assert
    assert actions.power_state(transport) == "awake"


def test_power_state_does_not_use_grep_m1() -> None:
    """`grep -m1` closes the pipe on a still-writing dumpsys, which prints
    "Failed to write while dumping service power" into the merged stream and
    makes a clean read look like a failure."""
    # Arrange
    transport = FakeTransport(responses=AWAKE)

    # Act
    actions.power_state(transport)

    # Assert
    assert not [command for command in transport.commands() if "-m1" in command]


def test_device_power_reports_an_awake_device(tmp_path: Path) -> None:
    # Arrange
    toolkit, _ = _toolkit(tmp_path, AWAKE)

    # Act
    reading = toolkit.device_power("stub-1")

    # Assert
    assert reading == {"device": "stub-1", "reachable": True, "state": "awake", "awake": True}


def test_device_power_reports_a_sleeping_device_as_reachable_but_not_awake(tmp_path: Path) -> None:
    """The whole point: a set-top box answers ping, TCP and ADB while asleep,
    so reachability cannot stand in for "someone is watching it"."""
    # Arrange
    toolkit, _ = _toolkit(tmp_path, ASLEEP)

    # Act
    reading = toolkit.device_power("stub-1")

    # Assert
    assert reading["reachable"] is True
    assert reading["awake"] is False
    assert reading["state"] == "asleep"


def test_device_power_never_raises_for_an_unreachable_device(tmp_path: Path) -> None:
    """A poller needs "not answering" as a value, not an exception."""
    # Arrange
    toolkit, _ = _toolkit(tmp_path, {}, connect_fails=True)

    # Act
    reading = toolkit.device_power("stub-1")

    # Assert
    assert reading == {"device": "stub-1", "reachable": False, "state": "", "awake": False}


def test_a_device_that_answers_nothing_is_not_reported_awake(tmp_path: Path) -> None:
    """Silence must never read as awake — that would fire the trigger against
    a device nobody turned on."""
    # Arrange
    toolkit, _ = _toolkit(tmp_path, {WAKEFULNESS: ""})

    # Act
    reading = toolkit.device_power("stub-1")

    # Assert
    assert reading["awake"] is False
    assert reading["reachable"] is False


def test_device_power_reports_an_unknown_device_rather_than_failing(tmp_path: Path) -> None:
    # Arrange
    toolkit, _ = _toolkit(tmp_path, AWAKE)

    # Act / Assert
    assert toolkit.device_power("no-such-device")["reachable"] is False


def test_device_power_records_no_operation(tmp_path: Path) -> None:
    """The load-bearing assertion. Polled every 30s, an operation per read
    would bury real work in the timeline within an hour."""
    # Arrange
    toolkit, _ = _toolkit(tmp_path, AWAKE)
    before = len(toolkit.list_operations())

    # Act
    for _ in range(5):
        toolkit.device_power("stub-1")

    # Assert
    assert len(toolkit.list_operations()) == before


def test_device_power_closes_every_transport_it_opened(tmp_path: Path) -> None:
    """Polled forever, one leaked connection per read exhausts the device."""
    # Arrange
    toolkit, pack = _toolkit(tmp_path, AWAKE)

    # Act
    for _ in range(3):
        toolkit.device_power("stub-1")

    # Assert
    assert len(pack.opened) == 3
    assert all(transport.closed for transport in pack.opened)
