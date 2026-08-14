"""Sweep, identify, record: one scan, shared by every caller."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Sequence

from fleetctl.core.discovery.claim import Claim, claim_hosts
from fleetctl.core.discovery.sweep import Host, Sweeper
from fleetctl.core.errors import FleetError
from fleetctl.core.inventory.store import DeviceStore
from fleetctl.core.transport.base import Transport

if TYPE_CHECKING:
    from fleetctl.core.registry import DevicePack

LOGGER = logging.getLogger(__name__)

Connector = Callable[[str, str], Transport]
Sweep = Callable[[str], list[Host]]


@dataclass(frozen=True, slots=True)
class ScanOutcome:
    """What a scan found and what it changed.

    **PARAMETERS:**
        `subnet` (str): What was swept.  <br>
        `claims` (tuple[Claim, ...]): One per host that answered, in sweep order.  <br>
        `added` (int): Devices new to the inventory.  <br>
        `updated` (int): Existing devices whose details changed.  <br>
        `collapsed` (int): Stored records folded into a device already in the inventory. Explains a total that fell without anything being forgotten.  <br>
        `total` (int): Devices in the inventory afterwards.  <br>
        `written` (bool): Whether the inventory was written; false for a dry run.  <br>
    """

    subnet: str
    claims: tuple[Claim, ...] = ()
    added: int = 0
    updated: int = 0
    collapsed: int = 0
    total: int = 0
    written: bool = False

    @property
    def responded(self) -> int:
        """RETURNS: int: How many hosts answered the sweep."""
        return len(self.claims)

    @property
    def identified(self) -> tuple[Claim, ...]:
        """RETURNS: tuple[Claim, ...]: Hosts a pack recognized and that are usable."""
        return tuple(claim for claim in self.claims if claim.claimed)

    @property
    def recordable(self) -> tuple[Claim, ...]:
        """RETURNS: tuple[Claim, ...]: Hosts that belong in the inventory, including ones flagged unusable."""
        return tuple(claim for claim in self.claims if claim.recordable)

    @property
    def unauthorized(self) -> tuple[str, ...]:
        """RETURNS: tuple[str, ...]: Addresses that answered but refused this key. Actionable, unlike the merely unrecognized."""
        return tuple(claim.host.address for claim in self.claims if not claim.claimed and claim.unauthorized)

    @property
    def unrecognized(self) -> tuple[str, ...]:
        """RETURNS: tuple[str, ...]: Addresses no installed pack claimed. On a real subnet these are the overwhelming majority."""
        return tuple(claim.host.address for claim in self.claims if not claim.claimed and not claim.unauthorized)

    def summary(self) -> str:
        """RETURNS: str: One line describing the scan."""
        if not self.recordable:
            return f"{self.responded} host(s) answered on {self.subnet}; none were recognized"
        if not self.written:
            return f"{len(self.recordable)} device(s) found on {self.subnet}; inventory not written"
        line = f"{len(self.recordable)} device(s) on {self.subnet}: {self.added} added, {self.updated} updated"
        return f"{line}, {self.collapsed} duplicate(s) collapsed" if self.collapsed else line

    def facts(self) -> dict[str, object]:
        """RETURNS: dict[str, object]: The scan as structured values for a caller that is not a terminal."""
        return {
            "subnet": self.subnet,
            "responded": self.responded,
            "identified": [claim.device.id for claim in self.identified if claim.device is not None],
            "unauthorized": list(self.unauthorized),
            "unrecognized": len(self.unrecognized),
            "added": self.added,
            "updated": self.updated,
            "collapsed": self.collapsed,
            "total": self.total,
            "written": self.written,
        }


@dataclass(frozen=True, slots=True)
class Scanner:
    """Runs a scan and merges the result into an inventory.

    **PARAMETERS:**
        `packs` (Sequence[DevicePack]): Installed packs, in probe order.  <br>
        `connect` (Connector): Opens a transport for an address and platform.  <br>
        `inventory` (DeviceStore): Where recognized devices are recorded.  <br>
        `sweep` (Sweep): How to find hosts. Defaults to an ICMP sweep.  <br>
    """

    packs: Sequence[DevicePack]
    connect: Connector
    inventory: DeviceStore
    sweep: Sweep = field(default_factory=lambda: Sweeper().sweep)

    def run(self, subnet: str, *, dry_run: bool = False, log: Callable[[str], None] | None = None) -> ScanOutcome:
        """Sweep `subnet`, identify what answered, and record it.

        Unauthorized devices are recorded too, flagged rather than dropped:
        you can see something is there and what to do about it.

        **PARAMETERS:**
            `subnet` (str): CIDR block to sweep.  <br>
            `dry_run` (bool): Report findings without writing the inventory. Defaults to ``False``.  <br>
            `log` (Callable[[str], None] | None): Progress sink. Defaults to ``None``.  <br>

        **RETURNS:**
            `ScanOutcome`: What answered, what was identified, and what changed.  <br>

        **RAISES:**
            `FleetError`: If `subnet` is unusable or no device packs are installed.  <br>
        """
        if not self.packs:
            raise FleetError("No device packs are installed, so nothing can be identified.")

        note = log or (lambda message: None)
        hosts = self.sweep(subnet)
        note(f"{len(hosts)} host(s) responded on {subnet}")

        claims = tuple(claim_hosts(hosts, self.packs, self.connect))
        outcome = ScanOutcome(subnet=subnet, claims=claims)
        for claim in outcome.identified:
            if claim.device is not None:
                note(f"{claim.device.id} ({claim.pack_id}) at {claim.host.address}")

        if not outcome.recordable or dry_run:
            return outcome

        devices = [claim.device for claim in outcome.recordable if claim.device is not None]
        result = self.inventory.reconcile(devices)
        note(f"{result.added} added, {result.updated} updated")
        if result.collapsed:
            note(f"{result.collapsed} duplicate record(s) collapsed")
        return ScanOutcome(
            subnet=subnet,
            claims=claims,
            added=result.added,
            updated=result.updated,
            collapsed=result.collapsed,
            total=len(result.devices),
            written=True,
        )
