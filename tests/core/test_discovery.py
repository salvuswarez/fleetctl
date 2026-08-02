"""Tests for network sweep and pack-based host claiming."""

from __future__ import annotations

from typing import Callable, Iterable, Mapping

import pytest

from fleetctl.core.discovery.claim import Claim, claim_host, claim_hosts, device_id_for
from fleetctl.core.discovery.sweep import Host, Sweeper, arp_table, expand_subnet
from fleetctl.core.effects import Capability
from fleetctl.core.errors import ConfigError, TransportError
from fleetctl.core.registry import RegisteredStep
from fleetctl.core.transport.base import CommandRunner, Transport
from fleetctl.core.transport.fake import FakeTransport

FIRE_FACTS = {
    "getprop ro.product.model": "AFTKA",
    "getprop ro.product.manufacturer": "Amazon",
    "getprop ro.serialno": "FIRE123",
    "getprop ro.build.version.release": "9",
    "settings get global device_name": "Living Room",
}


class _Pack:
    """A pack that claims hosts whose model matches its own."""

    def __init__(self, pack_id: str, manufacturer: str, *, platform: str = "android", priority: int = 10, explode: bool = False) -> None:
        self.id = pack_id
        self.platform = platform
        self.capabilities = frozenset({Capability.EXEC})
        self.probe_priority = priority
        self._manufacturer = manufacturer
        self._explode = explode

    def probe(self, runner: CommandRunner) -> dict[str, str] | None:
        if self._explode:
            raise RuntimeError("probe blew up")
        manufacturer = runner.exec_ok("getprop ro.product.manufacturer")
        if self._manufacturer.lower() not in manufacturer.lower():
            return None
        return {
            "type": self.id,
            "model": runner.exec_ok("getprop ro.product.model"),
            "serial": runner.exec_ok("getprop ro.serialno"),
            "name": runner.exec_ok("settings get global device_name"),
        }

    def steps(self) -> Iterable[RegisteredStep]:
        return []


def _connector(transports: Mapping[str, Transport]) -> Callable[[str, str], Transport]:
    def _connect(address: str, platform: str) -> Transport:
        if address not in transports:
            raise TransportError("nothing listening", target=address)
        return transports[address]

    return _connect


@pytest.mark.parametrize(
    ("subnet", "first", "count"),
    [("192.168.1.0/24", "192.168.1.1", 254), ("192.168.1", "192.168.1.1", 254), ("10.0.0.0/30", "10.0.0.1", 2)],
)
def test_a_subnet_expands_to_host_addresses(subnet: str, first: str, count: int) -> None:
    # Act
    addresses = expand_subnet(subnet)

    # Assert
    assert addresses[0] == first
    assert len(addresses) == count


@pytest.mark.parametrize("subnet", ["not-a-subnet", "192.168.1.0/8", ""])
def test_an_unusable_subnet_is_refused_with_a_reason(subnet: str) -> None:
    """A /8 is a mistake rather than an intention, and sweeping it would take
    hours before failing."""
    # Act / Assert
    with pytest.raises(ConfigError):
        expand_subnet(subnet)


def test_the_arp_table_degrades_rather_than_failing(monkeypatch: pytest.MonkeyPatch) -> None:
    """No MAC is a worse scan, not a failed one."""

    # Arrange
    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError("arp not found")

    monkeypatch.setattr("fleetctl.core.discovery.sweep.subprocess.run", _boom)

    # Act / Assert
    assert arp_table() == {}


def test_a_pack_claims_a_host_it_recognizes() -> None:
    # Arrange
    host = Host(address="192.168.1.50", mac="aa:bb:cc:dd:ee:ff")
    packs = [_Pack("firetv", "Amazon"), _Pack("shield", "NVIDIA")]

    # Act
    claim = claim_host(host, packs, _connector({"192.168.1.50": FakeTransport(responses=FIRE_FACTS)}))

    # Assert
    assert claim.claimed
    assert claim.pack_id == "firetv"
    assert claim.device is not None
    assert claim.device.model == "AFTKA"
    assert claim.device.mac == "aa:bb:cc:dd:ee:ff"


def test_an_unrecognized_host_is_reported_not_dropped() -> None:
    """A sweep finds printers and laptops. That is a normal result, and the
    predecessor's definition of a device excluded them by construction."""
    # Arrange
    host = Host(address="192.168.1.99")
    printer = FakeTransport(responses={"getprop ro.product.manufacturer": ""})

    # Act
    claim = claim_host(host, [_Pack("firetv", "Amazon")], _connector({"192.168.1.99": printer}))

    # Assert
    assert claim.claimed is False
    assert claim.host.address == "192.168.1.99"


def test_an_unreachable_host_is_not_an_error() -> None:
    # Act
    claim = claim_host(Host(address="192.168.1.7"), [_Pack("firetv", "Amazon")], _connector({}))

    # Assert
    assert claim.claimed is False


def test_a_probe_that_raises_does_not_abort_the_scan() -> None:
    """The predecessor lost whole sweeps to one unresponsive host."""
    # Arrange
    packs = [_Pack("broken", "Amazon", priority=1, explode=True), _Pack("firetv", "Amazon", priority=2)]

    # Act
    claim = claim_host(Host(address="192.168.1.50"), packs, _connector({"192.168.1.50": FakeTransport(responses=FIRE_FACTS)}))

    # Assert
    assert claim.pack_id == "firetv"


def test_one_connection_is_shared_across_packs_on_the_same_platform() -> None:
    """An unreachable host should cost one failed connection, not one per
    installed pack."""
    # Arrange
    attempts: list[str] = []

    def _connect(address: str, platform: str) -> Transport:
        attempts.append(platform)
        return FakeTransport(responses=FIRE_FACTS)

    packs = [_Pack("shield", "NVIDIA"), _Pack("firetv", "Amazon")]

    # Act
    claim_host(Host(address="192.168.1.50"), packs, _connect)

    # Assert
    assert attempts == ["android"]


def test_packs_on_different_platforms_each_get_a_connection() -> None:
    # Arrange
    attempts: list[str] = []

    def _connect(address: str, platform: str) -> Transport:
        attempts.append(platform)
        if platform == "android":
            raise TransportError("no adb here", target=address)
        return FakeTransport(responses={"getprop ro.product.manufacturer": "Acme"})

    packs = [_Pack("firetv", "Amazon"), _Pack("box", "Acme", platform="ssh")]

    # Act
    claim = claim_host(Host(address="192.168.1.70"), packs, _connect)

    # Assert
    assert attempts == ["android", "ssh"]
    assert claim.pack_id == "box"


@pytest.mark.parametrize(
    ("facts", "mac", "expected"),
    [
        ({"name": "Living Room"}, "aa:bb:cc:dd:ee:ff", "living-room"),
        ({"serial": "FIRE123"}, "aa:bb:cc:dd:ee:ff", "fire123"),
        ({}, "aa:bb:cc:dd:ee:ff", "aabbccddeeff"),
        ({}, "", "192-168-1-50"),
    ],
)
def test_the_device_id_prefers_something_stable_over_the_address(facts: dict[str, str], mac: str, expected: str) -> None:
    """An id derived from the address would make every DHCP renewal look like
    a new device."""
    # Act / Assert
    assert device_id_for(facts, Host(address="192.168.1.50", mac=mac)) == expected


def test_many_hosts_are_claimed_concurrently() -> None:
    # Arrange
    hosts = [Host(address=f"192.168.1.{index}") for index in range(50, 55)]
    transports: Mapping[str, Transport] = {host.address: FakeTransport(responses=FIRE_FACTS) for host in hosts}

    # Act
    claims = claim_hosts(hosts, [_Pack("firetv", "Amazon")], _connector(transports))

    # Assert
    assert len(claims) == 5
    assert all(claim.claimed for claim in claims)


def test_claiming_nothing_is_cheap_and_safe() -> None:
    assert claim_hosts([], [_Pack("firetv", "Amazon")], _connector({})) == []


def test_a_claim_carries_the_host_even_when_unclaimed() -> None:
    # Act
    claim = Claim(host=Host(address="192.168.1.9"))

    # Assert
    assert claim.claimed is False
    assert claim.host.address == "192.168.1.9"


class _Finished:
    """Stands in for a completed subprocess."""

    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def test_a_sweep_returns_only_hosts_that_answered(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    alive = {"10.0.0.1", "10.0.0.3"}

    def _run(command: list[str], **kwargs: object) -> _Finished:
        if command[0] == "arp":
            return _Finished(stdout="  10.0.0.1  aa-bb-cc-dd-ee-ff  dynamic")
        return _Finished(returncode=0 if command[-1] in alive else 1)

    monkeypatch.setattr("fleetctl.core.discovery.sweep.subprocess.run", _run)

    # Act
    hosts = Sweeper(workers=4).sweep("10.0.0.0/29")

    # Assert
    assert sorted(host.address for host in hosts) == ["10.0.0.1", "10.0.0.3"]


def test_a_sweep_attaches_macs_from_the_arp_table(monkeypatch: pytest.MonkeyPatch) -> None:
    """A MAC is what survives a DHCP lease change."""

    # Arrange
    def _run(command: list[str], **kwargs: object) -> _Finished:
        if command[0] == "arp":
            return _Finished(stdout="  10.0.0.1  aa-bb-cc-dd-ee-ff  dynamic\n  10.0.0.2  incomplete")
        return _Finished(returncode=0 if command[-1] == "10.0.0.1" else 1)

    monkeypatch.setattr("fleetctl.core.discovery.sweep.subprocess.run", _run)

    # Act
    hosts = Sweeper(workers=2).sweep("10.0.0.0/29")

    # Assert
    assert hosts[0].mac == "aa:bb:cc:dd:ee:ff"


def test_a_ping_that_cannot_run_drops_the_host_rather_than_the_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    def _run(command: list[str], **kwargs: object) -> _Finished:
        if command[0] == "arp":
            return _Finished(stdout="")
        raise OSError("ping is not installed")

    monkeypatch.setattr("fleetctl.core.discovery.sweep.subprocess.run", _run)

    # Act / Assert
    assert Sweeper(workers=2).sweep("10.0.0.0/30") == []
