"""The device record."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DeviceStatus(str, Enum):
    """Whether a device can currently be acted on."""

    OK = "ok"
    UNAUTHORIZED = "unauthorized"

    @property
    def is_actionable(self) -> bool:
        """RETURNS: bool: Whether steps may be scheduled against this device."""
        return self is DeviceStatus.OK


class Device(BaseModel):
    """One device in the fleet.

    **PARAMETERS:**
        `id` (str): Stable identifier, unique within the inventory.  <br>
        `type` (str): Which device pack claims it, e.g. ``firetv``. Empty until a probe claims it.  <br>
        `address` (str): Current network address.  <br>
        `mac` (str): MAC address, lowercase colon-separated, or empty if unknown.  <br>
        `name` (str): Human-readable name.  <br>
        `model` (str): Vendor model string.  <br>
        `serial` (str): Vendor serial number.  <br>
        `os_version` (str): Operating system release string.  <br>
        `status` (DeviceStatus): Whether the device can currently be acted on. Discovery sets `unauthorized` for a host that answered but refused this key.  <br>
        `tags` (list[str]): Free-form labels used for workflow targeting and policy matching.  <br>
        `vars` (dict[str, Any]): Per-app and per-device state, namespaced by app id. The kernel never interprets these.  <br>
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    type: str = ""
    address: str = ""
    mac: str = ""
    name: str = ""
    model: str = ""
    serial: str = ""
    os_version: str = ""
    status: DeviceStatus = DeviceStatus.OK
    tags: list[str] = Field(default_factory=list)
    vars: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_actionable(self) -> bool:
        """RETURNS: bool: Whether steps may be scheduled against this device."""
        return self.status.is_actionable

    def has_tag(self, tag: str) -> bool:
        """RETURNS: bool: Whether this device carries `tag`."""
        return tag in self.tags

    def app_vars(self, app_id: str) -> dict[str, Any]:
        """Return the variables namespaced to one app.

        **PARAMETERS:**
            `app_id` (str): The app pack's id, e.g. ``kodi``.  <br>

        **RETURNS:**
            `dict[str, Any]`: That app's variables, or an empty dict.  <br>
        """
        value = self.vars.get(app_id)
        return dict(value) if isinstance(value, dict) else {}
