"""Turning hosts into devices: which pack recognizes what."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Sequence

from fleetctl.core.discovery.sweep import Host
from fleetctl.core.errors import DeviceUnauthorizedError, FleetError, TransportError
from fleetctl.core.inventory.device import Device, DeviceStatus
from fleetctl.core.registry import DevicePack
from fleetctl.core.transport.base import Transport

LOGGER = logging.getLogger(__name__)

_PROBE_WORKERS = 8

Connector = Callable[[str, str], Transport]
"""Opens a transport to an address for a platform. Raises `TransportError` if it cannot."""


@dataclass(frozen=True, slots=True)
class Claim:
    """What discovery concluded about one host.

    **PARAMETERS:**
        `host` (Host): The address that answered.  <br>
        `device` (Device | None): The device it turned out to be, or None if nothing claimed it.  <br>
        `pack_id` (str): Which pack claimed it, empty when unclaimed.  <br>
        `unauthorized` (bool): Whether a transport reached the host but was refused. Actionable — the device needs to approve this key.  <br>
    """

    host: Host
    device: Device | None = None
    pack_id: str = ""
    unauthorized: bool = False

    @property
    def claimed(self) -> bool:
        """RETURNS: bool: Whether a pack recognized this host."""
        return self.device is not None and self.device.is_actionable

    @property
    def recordable(self) -> bool:
        """RETURNS: bool: Whether this belongs in the inventory at all."""
        return self.device is not None


def device_id_for(facts: dict[str, str], host: Host) -> str:
    """Derive a stable identifier for a discovered device.

    **PARAMETERS:**
        `facts` (dict[str, str]): What the claiming pack reported.  <br>
        `host` (Host): The address and MAC it was found at.  <br>

    **RETURNS:**
        `str`: A slug safe to use as an inventory key.  <br>
    """
    for candidate in (facts.get("name", ""), facts.get("serial", ""), host.mac.replace(":", "")):
        slug = _slugify(candidate)
        if slug:
            return slug
    return _slugify(host.address) or "unknown-device"


def _slugify(value: str) -> str:
    cleaned = "".join(character if character.isalnum() else "-" for character in value.strip().lower())
    return "-".join(part for part in cleaned.split("-") if part)[:48]


def claim_host(host: Host, packs: Sequence[DevicePack], connect: Connector) -> Claim:
    """Ask each pack, in order, whether it recognizes a host.

    **PARAMETERS:**
        `host` (Host): The address to identify.  <br>
        `packs` (Sequence[DevicePack]): Packs in probe order.  <br>
        `connect` (Connector): Opens a transport for a given address and platform.  <br>

    **RETURNS:**
        `Claim`: The device if something claimed it, otherwise an unclaimed result. Never raises: a host that cannot be reached is a normal outcome of sweeping a network.  <br>
    """
    unauthorized = False
    for pack_platform, platform_packs in _by_platform(packs).items():
        transport: Transport | None = None
        try:
            transport = connect(host.address, pack_platform)
        except DeviceUnauthorizedError as exc:
            LOGGER.info("%s refused this key: %s", host.address, exc)
            unauthorized = True
            continue
        except TransportError as exc:
            LOGGER.debug("No %s transport to %s: %s", pack_platform, host.address, exc)
            continue
        except FleetError as exc:
            # Anything else a pack raises building a transport — a malformed
            # credential, an unusable path — is that platform's problem, not
            # this host's and not the sweep's. A fleet-wide scan died on the
            # first host because one pack's SSH identity was misconfigured,
            # finding nothing at all when every ADB device was reachable.
            # WARNING rather than debug: unlike an unreachable host, this is
            # not a normal outcome and someone has to fix it.
            LOGGER.warning("Cannot build a %s transport for %s: %s", pack_platform, host.address, exc)
            continue
        try:
            for pack in platform_packs:
                facts = _probe(pack, transport, host)
                if facts is not None:
                    return Claim(host=host, device=_device_from(facts, host), pack_id=pack.id)
        finally:
            transport.close()
    if unauthorized:
        # Recorded rather than dropped: the user needs to see that something
        # is there and what to do about it.
        return Claim(host=host, device=_unauthorized_device(host), unauthorized=True)
    return Claim(host=host)


def _probe(pack: DevicePack, transport: Transport, host: Host) -> dict[str, str] | None:
    """Run one pack's probe, treating a raised error as "not mine"."""
    try:
        return pack.probe(transport)
    except Exception as exc:  # noqa: BLE001 - a bad probe is not a fatal scan
        LOGGER.warning("Probe %s failed for %s: %s", pack.id, host.address, exc)
        return None


def _device_from(facts: dict[str, str], host: Host) -> Device:
    return Device(
        id=device_id_for(facts, host),
        type=facts.get("type", ""),
        address=host.address,
        mac=host.mac,
        name=facts.get("name", ""),
        model=facts.get("model", ""),
        serial=facts.get("serial", ""),
        os_version=facts.get("os_version", ""),
        abi=facts.get("abi", ""),
        abilist=facts.get("abilist", ""),
    )


def _unauthorized_device(host: Host) -> Device:
    """Build the inventory record for a host that refused our credentials."""
    return Device(
        id=device_id_for({}, host),
        address=host.address,
        mac=host.mac,
        status=DeviceStatus.UNAUTHORIZED,
    )


def _by_platform(packs: Sequence[DevicePack]) -> dict[str, list[DevicePack]]:
    grouped: dict[str, list[DevicePack]] = {}
    for pack in packs:
        grouped.setdefault(pack.platform, []).append(pack)
    return grouped


def claim_hosts(hosts: Sequence[Host], packs: Sequence[DevicePack], connect: Connector, *, workers: int = _PROBE_WORKERS) -> list[Claim]:
    """Identify many hosts concurrently.

    **PARAMETERS:**
        `hosts` (Sequence[Host]): What the sweep found.  <br>
        `packs` (Sequence[DevicePack]): Packs in probe order.  <br>
        `connect` (Connector): Opens a transport for a given address and platform.  <br>
        `workers` (int): How many hosts to probe at once.  <br>

    **RETURNS:**
        `list[Claim]`: One per host, in the order given.  <br>
    """
    if not hosts:
        return []
    with ThreadPoolExecutor(max_workers=min(workers, len(hosts)), thread_name_prefix="fleetctl-probe") as pool:
        return list(pool.map(lambda host: claim_host(host, packs, connect), hosts))
