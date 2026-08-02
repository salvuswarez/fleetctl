"""Per-device Kodi configuration, applied after a profile is restored."""

from __future__ import annotations

import logging
import posixpath
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any, Mapping

from ...core.effects import Capability, Effect
from ...core.errors import FleetError
from ...core.workflow.step import DeviceStepContext, StepResult, StepSpec
from .spec import state_spec

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
            LOGGER.debug("Setting %s absent from %s, skipping", setting_id, relative)
            continue
        if (element.text or "") != value:
            element.text = value
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
    block = tree.getroot().find(".//resolution")
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
