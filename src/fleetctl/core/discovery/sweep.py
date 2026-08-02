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

# Each ping is a subprocess with a captured pipe, and Windows' subprocess
# reader threads fall over well before 50 of those run at once — the failure
# is a crashed reader thread and a `None` stdout, not a clean error. Sixteen
# sweeps a /24 in well under a minute and is stable.
_PING_WORKERS = 16
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
        is_windows = platform.system() == "Windows"
        command = ["ping", "-n", str(self.count), "-w", "1000", address] if is_windows else ["ping", "-c", str(self.count), "-W", "1", address]
        try:
            finished = subprocess.run(
                command,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=_PING_TIMEOUT_S * self.count,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            LOGGER.debug("Ping failed for %s: %s", address, exc)
            return None
        # stdout can come back None if the reader thread died under load;
        # treat that as "no evidence it replied" rather than crashing a sweep.
        return address if replied(finished.stdout or "", returncode=finished.returncode, is_windows=is_windows) else None


def replied(output: str, *, returncode: int, is_windows: bool) -> bool:
    """Decide whether a host actually answered a ping.

    Windows `ping` exits **0 even when nothing replied**: the local router
    answers "Destination host unreachable" on behalf of dead addresses, and
    that counts as the command succeeding. Trusting the exit code reported
    252 of 254 addresses on a real /24 as live — every empty address in the
    range. The reply text is the only reliable signal, so a real echo reply
    (`TTL=`) is required, and an unreachable/timeout reply is rejected even
    when the exit code says otherwise.

    POSIX `ping` reports total loss through its exit code, so there the code
    is authoritative.

    **PARAMETERS:**
        `output` (str): The command's stdout.  <br>
        `returncode` (int): Its exit status.  <br>
        `is_windows` (bool): Which convention to apply.  <br>

    **RETURNS:**
        `bool`: Whether the host genuinely answered.  <br>
    """
    if not is_windows:
        return returncode == 0
    lowered = output.lower()
    if "unreachable" in lowered or "timed out" in lowered or "100% loss" in lowered:
        return False
    return "ttl=" in lowered


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
