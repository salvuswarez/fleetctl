"""The device record."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from fleetctl.core.errors import ConfigError

# A tag is matched literally by workflow `targets`, by `policy.protected`, and
# by `DeviceStore.select`. None of those normalize, so `Kodi` and `kodi` would
# be two different tags and only one of them would ever match anything.
_TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
MAX_TAG_LENGTH = 32


def normalize_tag(tag: str) -> str:
    """Fold a user-supplied tag into the one form everything matches on.

    Free text reaches this from a panel's tag field, and every consumer
    compares tags literally — so normalizing at the single write path is what
    keeps `Kodi`, ` kodi ` and `kodi` from becoming three tags that each match
    a different subset of the fleet, or nothing at all.

    **PARAMETERS:**
        `tag` (str): The tag as typed.  <br>

    **RETURNS:**
        `str`: Lowercased and trimmed.  <br>

    **RAISES:**
        `ConfigError`: If the result is empty, too long, or carries characters that would not survive a round trip through YAML and workflow matching.  <br>
    """
    folded = tag.strip().lower()
    if not folded:
        raise ConfigError("A tag cannot be empty")
    if len(folded) > MAX_TAG_LENGTH:
        raise ConfigError(f"Tag {folded!r} is longer than {MAX_TAG_LENGTH} characters")
    if not _TAG_PATTERN.match(folded):
        raise ConfigError(f"Tag {folded!r} must start with a letter or digit and use only letters, digits, dot, dash or underscore")
    return folded


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
        `abi` (str): The machine code this device prefers, e.g. ``arm64-v8a``. Empty when the pack does not report one.  <br>
        `abilist` (str): Every architecture it can execute, most-preferred first, comma-separated. The authority for compatibility: a 64-bit device usually still runs 32-bit, which `abi` alone does not say.  <br>
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
    abi: str = ""
    abilist: str = ""
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
