"""Merging discovery results into the known fleet. Pure: data in, data out."""

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
        `collapsed` (int): How many stored records turned out to be a second copy of a device already in the list.  <br>
    """

    devices: list[Device]
    added: int
    updated: int
    collapsed: int = 0


def _matches(existing: Device, found: Device) -> bool:
    if existing.mac and found.mac and existing.mac.lower() == found.mac.lower():
        return True
    # A MAC identifies an interface, the serial identifies the box: a device
    # that answered over ethernet once and wifi the next time reports two
    # MACs, and treating that as two devices is how a duplicate is born.
    if existing.serial and found.serial:
        return existing.serial == found.serial
    if existing.mac and found.mac:
        return False
    return bool(existing.address) and existing.address == found.address


def _is_duplicate(keeper: Device, other: Device) -> bool:
    # An id is unique within the inventory by definition, so a repeated one is
    # a duplicate even when no identity field can prove it.
    return keeper.id == other.id or _matches(keeper, other)


def _fold(keeper: Device, duplicate: Device) -> Device:
    """Fold a second record for the same hardware into the one being kept.

    Unlike `merge_device`, neither side is fresher than the other: both are
    stored records. The keeper wins every contested field, and the duplicate
    contributes only what the keeper lacks — including tags, which are
    hand-maintained and would otherwise be silently thrown away.

    **PARAMETERS:**
        `keeper` (Device): The record that stays, and whose id survives.  <br>
        `duplicate` (Device): The second record for the same device.  <br>

    **RETURNS:**
        `Device`: The keeper, enriched with whatever only the duplicate knew.  <br>
    """
    merged = keeper.model_dump(mode="json")
    for key, value in duplicate.model_dump(mode="json").items():
        if key == "id" or value in ("", None, [], {}):
            continue
        if key == "tags":
            merged["tags"] = [*keeper.tags, *(tag for tag in duplicate.tags if tag not in keeper.tags)]
        elif key == "vars":
            merged["vars"] = {**duplicate.vars, **keeper.vars}
        elif merged[key] in ("", None, [], {}):
            merged[key] = value
    return Device.model_validate(merged)


def collapse(devices: list[Device]) -> tuple[list[Device], int]:
    """Fold every repeated device in a stored fleet into its first record.

    Without this a duplicate is unremovable: discovery matches the first
    record, updates it, and writes both back, so every scan preserves the
    copy — and undoes a manual deletion of it.

    **PARAMETERS:**
        `devices` (list[Device]): The stored fleet, duplicates and all.  <br>

    **RETURNS:**
        `tuple[list[Device], int]`: The deduplicated fleet in its original order, and how many records were folded away.  <br>
    """
    kept: list[Device] = []
    folded = 0
    for device in devices:
        index = next((position for position, keeper in enumerate(kept) if _is_duplicate(keeper, device)), None)
        if index is None:
            kept.append(device)
        else:
            kept[index] = _fold(kept[index], device)
            folded += 1
    return kept, folded


def merge_device(existing: Device, found: Device) -> Device:
    """Overlay a discovered device onto a known one.

    **PARAMETERS:**
        `existing` (Device): The stored record.  <br>
        `found` (Device): What discovery reported.  <br>

    **RETURNS:**
        `Device`: The merged record. Fields the probe left empty keep their stored value, and `tags`/`vars` are never touched by discovery.  <br>
    """
    merged = existing.model_dump(mode="json")
    for key, value in found.model_dump(mode="json").items():
        if key in _PRESERVED_FIELDS or key == "id":
            continue
        if value not in ("", None, [], {}):
            merged[key] = value
    return Device.model_validate(merged)


def reconcile(existing: list[Device], discovered: list[Device]) -> ReconcileResult:
    """Merge discovery results into the known fleet, deduplicating it first.

    **PARAMETERS:**
        `existing` (list[Device]): The stored fleet.  <br>
        `discovered` (list[Device]): What a scan found.  <br>

    **RETURNS:**
        `ReconcileResult`: The merged fleet plus added/updated/collapsed counts. Devices that were not seen by this scan are retained unchanged — absence from a scan is not evidence a device is gone.  <br>
    """
    merged, collapsed = collapse(existing)
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

    # A second pass: a probe can hand a record the MAC that reveals it to be
    # the same device as another, which was not visible before the merge.
    merged, folded_after = collapse(merged)

    return ReconcileResult(devices=merged, added=added, updated=updated, collapsed=collapsed + folded_after)
