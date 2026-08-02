"""Tests for the scan step and the scanner both it and the CLI share."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Sequence

import pytest

from fleetctl.core.discovery.claim import Claim
from fleetctl.core.discovery.scan import Scanner
from fleetctl.core.discovery.step import SCAN, scan
from fleetctl.core.discovery.sweep import Host
from fleetctl.core.effects import Capability, Effect
from fleetctl.core.errors import FleetError
from fleetctl.core.inventory.device import Device, DeviceStatus
from fleetctl.core.inventory.store import DeviceStore
from fleetctl.core.operations.registry import OperationRegistry
from fleetctl.core.workflow.step import DiscoveryStepContext


class _Pack:
    id = "shield"
    platform = "android"
    capabilities = frozenset({Capability.EXEC})
    probe_priority = 10

    def probe(self, runner: Any) -> dict[str, str] | None:
        return None

    def steps(self) -> Iterable[Any]:
        return []


REGISTRY = OperationRegistry()


def _scanner(tmp_path: Path, hosts: Sequence[Host], packs: Sequence[Any] | None = None) -> Scanner:
    return Scanner(
        packs=[_Pack()] if packs is None else list(packs),
        connect=lambda address, platform: (_ for _ in ()).throw(AssertionError("no transport should be opened")),
        inventory=DeviceStore(tmp_path / "devices.yml"),
        sweep=lambda subnet: list(hosts),
    )


def _context(scanner: Scanner, tmp_path: Path, op_id: str = "op-1", **config: Any) -> DiscoveryStepContext:
    return DiscoveryStepContext(scanner=scanner, config=config, handle=REGISTRY.start(op_id, SCAN.id), workspace=tmp_path)


def _logs(op_id: str) -> list[str]:
    operation = REGISTRY.get(op_id)
    return [entry["message"] for entry in operation.logs] if operation else []


def _found(address: str = "192.168.1.50") -> Device:
    return Device(id="den-shield", type="shield", address=address, model="SHIELD Android TV")


def test_a_scan_records_what_it_identified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    host = Host(address="192.168.1.50", mac="aa:bb:cc:dd:ee:ff")
    scanner = _scanner(tmp_path, [host])
    monkeypatch.setattr("fleetctl.core.discovery.scan.claim_hosts", lambda hosts, packs, connect: [Claim(host=host, device=_found(), pack_id="shield")])

    # Act
    result = scan(_context(scanner, tmp_path, subnet="192.168.1.0/24"))

    # Assert
    assert result.facts["identified"] == ["den-shield"]
    assert result.facts["added"] == 1
    assert result.facts["written"] is True
    assert scanner.inventory.get("den-shield") is not None


def test_a_dry_run_finds_devices_without_writing_the_inventory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    host = Host(address="192.168.1.50")
    scanner = _scanner(tmp_path, [host])
    monkeypatch.setattr("fleetctl.core.discovery.scan.claim_hosts", lambda hosts, packs, connect: [Claim(host=host, device=_found(), pack_id="shield")])

    # Act
    result = scan(_context(scanner, tmp_path, subnet="192.168.1.0/24", dry_run=True))

    # Assert
    assert result.facts["written"] is False
    assert result.facts["added"] == 0
    assert scanner.inventory.list() == []


def test_a_device_that_refused_the_key_is_reported_not_dropped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """It is the one discovery result a user can act on."""
    # Arrange
    host = Host(address="192.168.1.79")
    refused = Claim(host=host, device=Device(id="unknown-79", address=host.address, status=DeviceStatus.UNAUTHORIZED), unauthorized=True)
    scanner = _scanner(tmp_path, [host])
    monkeypatch.setattr("fleetctl.core.discovery.scan.claim_hosts", lambda hosts, packs, connect: [refused])

    # Act
    result = scan(_context(scanner, tmp_path, op_id="refused-op", subnet="192.168.1.0/24"))

    # Assert
    assert result.facts["unauthorized"] == ["192.168.1.79"]
    assert result.facts["identified"] == []
    assert scanner.inventory.get("unknown-79") is not None
    assert any("refused this key" in message for message in _logs("refused-op"))


def test_unrecognized_hosts_are_counted_not_enumerated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """On a real /24 they are the overwhelming majority."""
    # Arrange
    hosts = [Host(address=f"192.168.1.{index}") for index in range(2, 12)]
    scanner = _scanner(tmp_path, hosts)
    monkeypatch.setattr("fleetctl.core.discovery.scan.claim_hosts", lambda h, packs, connect: [Claim(host=host) for host in hosts])

    # Act
    result = scan(_context(scanner, tmp_path, subnet="192.168.1.0/24"))

    # Assert
    assert result.facts["unrecognized"] == 10
    assert result.facts["responded"] == 10
    assert "none were recognized" in result.summary


def test_a_scan_without_a_subnet_says_what_to_pass(tmp_path: Path) -> None:
    # Act / Assert
    with pytest.raises(FleetError) as caught:
        scan(_context(_scanner(tmp_path, []), tmp_path))
    assert "subnet" in str(caught.value)


def test_a_scan_with_no_packs_installed_explains_itself(tmp_path: Path) -> None:
    """Without a pack nothing can identify a host, so an empty result would be a lie."""
    # Act / Assert
    with pytest.raises(FleetError) as caught:
        _scanner(tmp_path, [], packs=[]).run("192.168.1.0/24")
    assert "device packs" in str(caught.value)


def test_the_scan_step_is_mutating_and_needs_no_transport(tmp_path: Path) -> None:
    """It decides what to connect to, so it cannot be handed a transport."""
    # Assert
    assert SCAN.effect is Effect.MUTATING
    assert SCAN.requires == frozenset()
    assert SCAN.scope == "discovery"


def test_the_scan_workflow_ships_by_default() -> None:
    """A fleet with no config of its own should still be able to find itself."""
    # Act
    from fleetctl.core.workflow.workflow import builtin_workflows

    shipped = builtin_workflows()

    # Assert
    assert "fleet-scan" in shipped
    assert [step.use for step in shipped["fleet-scan"].steps] == ["fleet.scan"]
    assert shipped["fleet-scan"].steps[0].params["subnet"]
