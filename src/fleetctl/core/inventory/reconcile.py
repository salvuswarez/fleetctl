"""Merging discovery results into the known fleet. Pure: data in, data out.

Two rules carried forward from the predecessor, both learned the hard way:

Match by MAC, then serial, then address. Addresses drift with DHCP leases,
so matching on address alone duplicates a device that merely moved.

Only overwrite a field when the probe actually returned a value. A device
that was asleep or partially probed keeps what was already known, rather
than having its record blanked by a half-successful scan.
"""

from __future__ import annotations

from dataclasses import dataclass

from .device import Device

# Never touched by discovery: hand-maintained, or owned by an app pack.
_PRESERVED_FIELDS = ("tags", "vars")


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """Outcome of merging discovered devices into the known fleet.

    **PARAMETERS:**
        `devices` (list[Device]): The full merged fleet.  <br>
        `added` (int): How many devices were newly discovered.  <br>
        `updated` (int): How many existing devices this refreshed.  <br>
    """

    devices: list[Device]
    added: int
    updated: int


def _matches(existing: Device, found: Device) -> bool:
    if existing.mac and found.mac:
        return existing.mac.lower() == found.mac.lower()
    if existing.serial and found.serial:
        return existing.serial == found.serial
    return bool(existing.address) and existing.address == found.address


def merge_device(existing: Device, found: Device) -> Device:
    """Overlay a discovered device onto a known one.

    **PARAMETERS:**
        `existing` (Device): The stored record.  <br>
        `found` (Device): What discovery reported.  <br>

    **RETURNS:**
        `Device`: The merged record. Fields the probe left empty keep their stored value, and `tags`/`vars` are never touched by discovery.  <br>
    """
    merged = existing.model_dump()
    for key, value in found.model_dump().items():
        if key in _PRESERVED_FIELDS or key == "id":
            continue
        if value not in ("", None, [], {}):
            merged[key] = value
    return Device.model_validate(merged)


def reconcile(existing: list[Device], discovered: list[Device]) -> ReconcileResult:
    """Merge discovery results into the known fleet.

    **PARAMETERS:**
        `existing` (list[Device]): The stored fleet.  <br>
        `discovered` (list[Device]): What a scan found.  <br>

    **RETURNS:**
        `ReconcileResult`: The merged fleet plus added/updated counts. Devices that were not seen by this scan are retained unchanged — absence from a scan is not evidence a device is gone.  <br>
    """
    merged = list(existing)
    added = 0
    updated = 0

    for found in discovered:
        index = next((position for position, known in enumerate(merged) if _matches(known, found)), None)
        if index is None:
            merged.append(found)
            added += 1
        else:
            merged[index] = merge_device(merged[index], found)
            updated += 1

    return ReconcileResult(devices=merged, added=added, updated=updated)
