"""Per-device Kodi configuration, applied after a profile is restored."""

from __future__ import annotations

import logging
import posixpath
import shlex
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any, Mapping

from ...core.effects import Capability, Effect
from ...core.errors import FleetError
from ...core.workflow.step import DeviceStepContext, StepResult, StepSpec
from .spec import APP_ID, state_spec

LOGGER = logging.getLogger(__name__)

GUISETTINGS = "guisettings.xml"
RESOLUTION_SETTING = "videoscreen.resolution"
OVERSCAN_FIELDS = ("left", "top", "right", "bottom")

APPLY_DEVICE_CONFIG = StepSpec(
    id="kodi.apply_device_config",
    summary="Reapply a device's own Kodi display calibration and setting overrides.",
    effect=Effect.MUTATING,
    requires=frozenset({Capability.FILES, Capability.STATE}),
    scope="device",
)


def apply_device_config(context: DeviceStepContext) -> StepResult:
    """Apply this device's `vars.kodi` calibration and overrides.

    **PARAMETERS:**
        `context` (DeviceStepContext): The device, its resolved state manager, and config.  <br>

    **RETURNS:**
        `StepResult`: What changed, per file.  <br>

    **RAISES:**
        `FleetError`: If the configured values are malformed.  <br>
    """
    device_vars = context.device.app_vars("kodi")
    display = device_vars.get("display") or {}
    settings = device_vars.get("settings") or {}

    if not display and not settings:
        context.handle.log(f"{context.device.id} has no per-device Kodi config; nothing to apply.")
        return StepResult(summary=f"{context.device.id}: no per-device config", facts={"changes": 0})

    root = context.state.state_root(state_spec())
    changes: list[str] = []

    if display:
        validate_display(display)
        changes.extend(_apply_file(context, root, posixpath.join("userdata", GUISETTINGS), _display_overrides(display)))

    for relative, overrides in settings.items():
        if not isinstance(overrides, Mapping):
            raise FleetError(f"{context.device.id}: vars.kodi.settings.{relative} must be a mapping of setting id to value")
        changes.extend(_apply_file(context, root, posixpath.join("userdata", str(relative)), {str(k): str(v) for k, v in overrides.items()}))

    for change in changes:
        context.handle.log(f"  {change}")
    return StepResult(summary=f"{context.device.id}: applied {len(changes)} per-device change(s)", facts={"changes": len(changes)})


def validate_display(display: Mapping[str, Any]) -> None:
    """Check a device's stored calibration before it is applied.

    **PARAMETERS:**
        `display` (Mapping[str, Any]): ``{"resolution_index": int, "overscan": {...}}``, both optional.  <br>

    **RAISES:**
        `FleetError`: If nothing recognizable is present, or a value is not an integer.  <br>
    """
    resolution = display.get("resolution_index")
    overscan = display.get("overscan") or {}
    if resolution is None and not overscan:
        raise FleetError("display config needs resolution_index and/or overscan")
    if resolution is not None and not isinstance(resolution, int):
        raise FleetError(f"display.resolution_index must be an integer, got {resolution!r}")
    for field_name in OVERSCAN_FIELDS:
        value = overscan.get(field_name)
        if value is not None and not isinstance(value, int):
            raise FleetError(f"display.overscan.{field_name} must be an integer, got {value!r}")


def _display_overrides(display: Mapping[str, Any]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    resolution = display.get("resolution_index")
    if resolution is not None:
        overrides[RESOLUTION_SETTING] = str(resolution)
    return overrides


def _apply_file(context: DeviceStepContext, root: str, relative: str, overrides: Mapping[str, str]) -> list[str]:
    """Pull one config file, edit it, and push it back."""
    if not overrides:
        return []

    remote = posixpath.join(root, relative)
    local = context.workspace / relative.replace("/", "_")
    try:
        context.transport.get(remote, local)
    except FleetError as exc:
        LOGGER.info("Skipping %s on %s: %s", relative, context.device.id, exc)
        return []

    try:
        tree = ElementTree.parse(local)
    except ElementTree.ParseError as exc:
        LOGGER.warning("Could not parse %s from %s: %s", relative, context.device.id, exc)
        return []

    xml_root = tree.getroot()
    by_id = {element.get("id"): element for element in xml_root.iter("setting")}
    changed: list[str] = []
    for setting_id, value in overrides.items():
        element = by_id.get(setting_id)
        if element is None:
            # Created rather than skipped: a build is device-neutral, so the
            # settings a device most needs to override are exactly the ones
            # stripped out of it. Skipping made per-device display calibration
            # unappliable.
            element = ElementTree.SubElement(xml_root, "setting", {"id": setting_id})
        if (element.text or "") != value:
            element.text = value
            # `default="true"` asserts the value *is* the addon's default, and
            # Kodi is free to discard a setting marked that way. Leaving it set
            # on an overridden value writes a change that reads back correctly
            # and then does not take effect.
            element.attrib.pop("default", None)
            changed.append(f"{relative}: {setting_id} = {value}")

    if not changed:
        return []
    tree.write(local, encoding="utf-8", xml_declaration=True)
    context.transport.put(local, remote, effect=Effect.MUTATING)
    return changed


def apply_overscan(local_path: Path, overscan: Mapping[str, Any]) -> bool:
    """Write overscan bounds into the first resolution block of a settings file.

    **PARAMETERS:**
        `local_path` (Path): A local copy of the settings file.  <br>
        `overscan` (Mapping[str, Any]): Any of ``left``/``top``/``right``/``bottom``.  <br>

    **RETURNS:**
        `bool`: Whether anything changed.  <br>
    """
    try:
        tree = ElementTree.parse(local_path)
    except ElementTree.ParseError:
        return False
    block = tree.getroot().find(".//resolution/overscan")
    if block is None:
        return False
    changed = False
    for field_name in OVERSCAN_FIELDS:
        value = overscan.get(field_name)
        element = block.find(field_name)
        if value is None or element is None or element.text == str(value):
            continue
        element.text = str(value)
        changed = True
    if changed:
        tree.write(local_path, encoding="utf-8", xml_declaration=True)
    return changed


READ_DISPLAY = StepSpec(
    id="kodi.read_display",
    summary="Read a device's live Kodi display calibration into its inventory vars.",
    effect=Effect.MUTATING,
    requires=frozenset({Capability.EXEC, Capability.STATE}),
    scope="device",
)


def read_display(context: DeviceStepContext) -> StepResult:
    """Record what the device's own `guisettings.xml` says about its display.

    **PARAMETERS:**
        `context` (DeviceStepContext): The device, its transport, and its state manager.  <br>

    **RETURNS:**
        `StepResult`: Facts carry the calibration found, empty when the device has none.  <br>
    """
    root = context.state.state_root(state_spec())
    path = posixpath.join(root, "userdata", GUISETTINGS)
    xml = context.transport.exec_ok(f"cat {shlex.quote(path)}", effect=Effect.READ)

    display = parse_display(xml)
    if not display:
        # Kodi only writes a setting that differs from its default, so a
        # device nobody has calibrated genuinely has neither value.
        context.handle.log(f"{context.device.id} reports no display calibration")
        return StepResult(summary=f"{context.device.id}: no display calibration", facts={})

    device = context.inventory.get(context.device.id)
    if device is not None:
        app_vars = dict(device.vars)
        kodi_vars = dict(app_vars.get(APP_ID) or {})
        kodi_vars["display"] = display
        app_vars[APP_ID] = kodi_vars
        stored = device.model_copy(update={"vars": app_vars})
        context.inventory.save([stored if other.id == device.id else other for other in context.inventory.list()])

    context.handle.log(f"{context.device.id}: {display}")
    return StepResult(summary=f"{context.device.id}: display calibration recorded", facts=dict(display))


def parse_display(xml: str) -> dict[str, Any]:
    """Extract resolution index and overscan from a `guisettings.xml` body.

    **PARAMETERS:**
        `xml` (str): File contents, or ``""`` when it could not be read.  <br>

    **RETURNS:**
        `dict[str, Any]`: Any of ``resolution_index`` and ``overscan`` that were present.  <br>
    """
    if not xml.strip():
        return {}
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        LOGGER.debug("guisettings.xml did not parse; reporting no calibration")
        return {}

    found: dict[str, Any] = {}
    for setting in root.iter("setting"):
        if setting.get("id") == RESOLUTION_SETTING and (setting.text or "").strip().lstrip("-").isdigit():
            found["resolution_index"] = int((setting.text or "").strip())
            break

    # The first <resolution> block is the active one, matching what
    # apply_device_config writes back.
    block = root.find(".//resolution/overscan")
    if block is not None:
        overscan = {
            field: int((element.text or "").strip())
            for field in OVERSCAN_FIELDS
            if (element := block.find(field)) is not None and (element.text or "").strip().lstrip("-").isdigit()
        }
        if overscan:
            found["overscan"] = overscan
    return found
