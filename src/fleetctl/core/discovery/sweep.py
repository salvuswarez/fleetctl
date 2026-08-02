"""Finding hosts that are up, and their hardware addresses.

Knows nothing about device types. Its whole job is to narrow a /24 down to
the handful of addresses worth probing, so discovery does not pay a
connection attempt against 254 empty addresses.
"""

from __future__ import annotations

import ipaddress
import logging
import platform
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ..errors import ConfigError

LOGGER = logging.getLogger(__name__)

_PING_WORKERS = 50
_PING_TIMEOUT_S = 3
# Two packets, not one. A single dropped ICMP reply on a weak radio — older
# streaming sticks in particular — otherwise removes a live host from the
# sweep before it is ever probed.
_PING_COUNT = 2

_MAC_PATTERN = re.compile(r"([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}")
_IPV4_PATTERN = re.compile(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")


@dataclass(frozen=True, slots=True)
class Host:
    """An address that answered, before anything knows what it is.

    **PARAMETERS:**
        `address` (str): IPv4 address.  <br>
        `mac` (str): Hardware address from the ARP table, lowercase colon-separated, or empty.  <br>
    """

    address: str
    mac: str = ""


@dataclass(frozen=True, slots=True)
class Sweeper:
    """Pings a subnet and reads the ARP table.

    **PARAMETERS:**
        `workers` (int): Concurrent pings.  <br>
        `count` (int): Packets per host.  <br>
    """

    workers: int = _PING_WORKERS
    count: int = _PING_COUNT

    def sweep(self, subnet: str) -> list[Host]:
        """Find hosts that answer on a subnet.

        **PARAMETERS:**
            `subnet` (str): A CIDR block (``192.168.1.0/24``) or a three-octet prefix (``192.168.1``).  <br>

        **RETURNS:**
            `list[Host]`: Responding hosts, with MACs where the ARP table knew one.  <br>

        **RAISES:**
            `ConfigError`: If `subnet` cannot be parsed.  <br>
        """
        addresses = expand_subnet(subnet)
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            responded = [address for address in pool.map(self._ping, addresses) if address]

        arp = arp_table()
        return [Host(address=address, mac=arp.get(address, "")) for address in responded]

    def _ping(self, address: str) -> str | None:
        command = (
            ["ping", "-n", str(self.count), "-w", "1000", address] if platform.system() == "Windows" else ["ping", "-c", str(self.count), "-W", "1", address]
        )
        try:
            finished = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=_PING_TIMEOUT_S * self.count,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            LOGGER.debug("Ping failed for %s: %s", address, exc)
            return None
        return address if finished.returncode == 0 else None


def expand_subnet(subnet: str) -> list[str]:
    """Turn a subnet into the addresses worth pinging.

    **PARAMETERS:**
        `subnet` (str): CIDR block, or a three-octet prefix for convenience.  <br>

    **RETURNS:**
        `list[str]`: Host addresses, excluding network and broadcast.  <br>

    **RAISES:**
        `ConfigError`: If `subnet` is neither form, or is large enough that sweeping it is a mistake rather than an intention.  <br>
    """
    candidate = subnet.strip()
    if candidate.count(".") == 2 and "/" not in candidate:
        candidate = f"{candidate}.0/24"
    try:
        network = ipaddress.ip_network(candidate, strict=False)
    except ValueError as exc:
        raise ConfigError(f"Cannot parse subnet {subnet!r}; use '192.168.1.0/24' or '192.168.1'", key="subnet") from exc
    if network.num_addresses > 1024:
        raise ConfigError(f"Refusing to sweep {network} ({network.num_addresses} addresses); narrow it to /22 or smaller", key="subnet")
    return [str(address) for address in network.hosts()]


def arp_table() -> dict[str, str]:
    """Read the local ARP cache.

    A MAC is what makes a device identifiable across a DHCP lease change, so
    it is worth collecting even though the sweep itself does not need it.

    **RETURNS:**
        `dict[str, str]`: Address to lowercase colon-separated MAC. Empty when `arp` is unavailable, which is a degraded result rather than an error.  <br>
    """
    table: dict[str, str] = {}
    try:
        finished = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        LOGGER.warning("Could not read the ARP table; discovered devices will have no MAC: %s", exc)
        return table

    for line in finished.stdout.splitlines():
        address_match = _IPV4_PATTERN.search(line)
        mac_match = _MAC_PATTERN.search(line)
        if address_match and mac_match:
            table[address_match.group(1)] = mac_match.group(0).replace("-", ":").lower()
    return table
