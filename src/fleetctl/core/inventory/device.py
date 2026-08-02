"""The device record.

Deliberately free of any app's concerns. The predecessor's device model
carried `display` (Kodi resolution/overscan) and `settings` (Kodi setting
overrides) as core inventory fields, which meant a PC in the store had a
field meaning "Kodi videoscreen.resolution".

App state lives under `vars`, namespaced by the app that owns it. `apps.kodi`
reads `device.vars["kodi"]`; the kernel never looks inside.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
    tags: list[str] = Field(default_factory=list)
    vars: dict[str, Any] = Field(default_factory=dict)

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
