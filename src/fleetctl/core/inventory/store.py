"""Persisting the fleet."""

from __future__ import annotations

import builtins
import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Iterable

from fleetctl.core.config.loader import load_yaml_text
from fleetctl.core.errors import ConfigError, FleetError
from fleetctl.core.inventory.device import Device
from fleetctl.core.inventory.reconcile import ReconcileResult, reconcile

LOGGER = logging.getLogger(__name__)

_YAML_SUFFIXES = (".yml", ".yaml")


class DeviceStore:
    """Loads, persists, and reconciles the device inventory.

    **PARAMETERS:**
        `path` (Path): Inventory file. Format follows the extension — YAML for `.yml`/`.yaml`, JSON otherwise.  <br>
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._is_yaml = path.suffix.lower() in _YAML_SUFFIXES
        self._lock = threading.Lock()

    def list(self) -> builtins.list[Device]:
        """RETURNS: list[Device]: Every known device."""
        with self._lock:
            return self._load()

    def get(self, device_id: str) -> Device | None:
        """RETURNS: Device | None: The device with this id, if known."""
        with self._lock:
            return next((device for device in self._load() if device.id == device_id), None)

    def get_by_address(self, address: str) -> Device | None:
        """RETURNS: Device | None: The device at this address, if known."""
        with self._lock:
            return next((device for device in self._load() if device.address == address), None)

    def select(self, *, tags: Iterable[str] = (), device_type: str = "") -> builtins.list[Device]:
        """Select devices matching every supplied criterion.

        **PARAMETERS:**
            `tags` (Iterable[str]): Every tag a device must carry.  <br>
            `device_type` (str): Device pack id a device must have; empty matches any.  <br>

        **RETURNS:**
            `list[Device]`: Matching devices, in inventory order.  <br>
        """
        wanted = list(tags)
        with self._lock:
            devices = self._load()
        return [device for device in devices if all(device.has_tag(tag) for tag in wanted) and (not device_type or device.type == device_type)]

    def save(self, devices: builtins.list[Device]) -> None:
        """Replace the stored inventory with `devices`, atomically."""
        with self._lock:
            self._save(devices)

    def reconcile(self, discovered: builtins.list[Device]) -> ReconcileResult:
        """Merge discovered devices into the store under the write lock.

        **PARAMETERS:**
            `discovered` (list[Device]): What a scan found.  <br>

        **RETURNS:**
            `ReconcileResult`: The merged fleet plus added/updated counts.  <br>
        """
        with self._lock:
            result = reconcile(self._load(), discovered)
            self._save(result.devices)
            return result

    def forget(self, device_id: str) -> bool:
        """Drop one device from the inventory, persisting immediately.

        Deliberately explicit rather than automatic. `reconcile` keeps a device
        a scan did not see, because absence from one sweep is not evidence a
        device is gone — a box that is merely off would otherwise disappear and
        take its tags and per-app vars with it. Forgetting is therefore a
        decision someone makes, not something a failed ping does.

        A forgotten device comes back on the next scan that finds it, as a new
        record with no tags: the identity survives in the hardware, the
        annotations do not.

        **PARAMETERS:**
            `device_id` (str): Inventory id to drop.  <br>

        **RETURNS:**
            `bool`: Whether a device was removed. ``False`` when the id is unknown, which is not an error — the caller wanted it gone and it is.  <br>
        """
        with self._lock:
            devices = self._load()
            remaining = [device for device in devices if device.id != device_id]
            if len(remaining) == len(devices):
                return False
            self._save(remaining)
            return True

    def set_tag(self, device_id: str, tag: str, *, exclusive: bool = False) -> Device:
        """Add `tag` to one device, persisting immediately.

        A scan never touches tags — this is the one path that mutates them
        programmatically, for a caller like a UI action that wants to change
        something scan-derived fields can't express.

        **PARAMETERS:**
            `device_id` (str): The device to tag.  <br>
            `tag` (str): Tag to add.  <br>
            `exclusive` (bool): If true, remove `tag` from every other device first — for a tag that names a single canonical device, like ``gold``.  <br>

        **RETURNS:**
            `Device`: The updated device.  <br>

        **RAISES:**
            `FleetError`: If `device_id` is not in the inventory.  <br>
        """
        with self._lock:
            devices = self._load()
            if not any(device.id == device_id for device in devices):
                raise FleetError(f"Unknown device: {device_id}")

            updated: builtins.list[Device] = []
            result: Device | None = None
            for device in devices:
                if device.id == device_id:
                    if tag not in device.tags:
                        device = device.model_copy(update={"tags": [*device.tags, tag]})
                    result = device
                elif exclusive and tag in device.tags:
                    device = device.model_copy(update={"tags": [existing for existing in device.tags if existing != tag]})
                updated.append(device)

            self._save(updated)
            assert result is not None
            return result

    def clear_tag(self, device_id: str, tag: str) -> Device:
        """Remove `tag` from one device, persisting immediately.

        The counterpart to `set_tag`, and required for the same reason it is:
        a tag is the only device annotation a scan never overwrites, so it is
        also the only one nothing else can undo. Without this, a tag applied
        by a UI action could be removed only by editing the inventory file or
        by forgetting the device — which discards its `vars` as well.

        Removing a tag a device does not carry is not an error: the caller
        wanted it gone and it is.

        **PARAMETERS:**
            `device_id` (str): The device to untag.  <br>
            `tag` (str): Tag to remove.  <br>

        **RETURNS:**
            `Device`: The updated device.  <br>

        **RAISES:**
            `FleetError`: If `device_id` is not in the inventory.  <br>
        """
        with self._lock:
            devices = self._load()
            if not any(device.id == device_id for device in devices):
                raise FleetError(f"Unknown device: {device_id}")

            updated: builtins.list[Device] = []
            result: Device | None = None
            for device in devices:
                if device.id == device_id:
                    if tag in device.tags:
                        device = device.model_copy(update={"tags": [existing for existing in device.tags if existing != tag]})
                    result = device
                updated.append(device)

            self._save(updated)
            assert result is not None
            return result

    def _load(self) -> builtins.list[Device]:
        if not self._path.exists():
            return []
        try:
            with open(self._path, encoding="utf-8") as handle:
                data: Any = self._parse(handle.read())
        except (OSError, ValueError) as exc:
            raise ConfigError(f"Could not read inventory at {self._path}: {exc}", key=str(self._path)) from exc
        if not isinstance(data, dict) or "devices" not in data:
            return []
        return [Device.model_validate(raw) for raw in data["devices"]]

    def _parse(self, text: str) -> Any:
        if self._is_yaml:
            return load_yaml_text(text, source=str(self._path))
        return json.loads(text)

    def _save(self, devices: builtins.list[Device]) -> None:
        # `mode="json"` so enums serialize as their values; a plain dump hands
        # YAML the enum object itself, which it cannot represent.
        payload = {"devices": [device.model_dump(mode="json") for device in devices]}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_name(f"{self._path.name}.{uuid.uuid4().hex}.tmp")
        with open(temp_path, "w", encoding="utf-8") as handle:
            handle.write(self._render(payload))
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(self._path)
        LOGGER.info("Saved %d devices to %s", len(devices), self._path)

    def _render(self, payload: dict[str, Any]) -> str:
        if self._is_yaml:
            import yaml

            return str(yaml.safe_dump(payload, default_flow_style=False, sort_keys=False))
        return json.dumps(payload, indent=2)
