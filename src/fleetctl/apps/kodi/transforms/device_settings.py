"""Strip one device's hardware configuration out of a shared build."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

LOGGER = logging.getLogger(__name__)

GUI_SETTINGS = "guisettings.xml"

# Settings describing the captured machine rather than how the fleet should be
# configured. Defaults; a recipe overrides them.
#
# `videoscreen.resolution` is a mode index into the captured device's own mode
# list, and the audio device strings name a platform-specific sink. Kodi
# rewrites those two device strings at startup but leaves `passthrough`,
# stranding a device passing through to a receiver that is not there.
DEVICE_SETTINGS: tuple[str, ...] = (
    "videoscreen.resolution",
    "videoscreen.monitor",
    "videoscreen.screen",
    "audiooutput.audiodevice",
    "audiooutput.passthroughdevice",
    "audiooutput.passthrough",
)

# Per-resolution overscan, pixel ratio and refresh rate measured against one
# physical panel. Worse than having none on a different panel: entries can hold
# `refreshrate 0.000000`, feeding a zero to Kodi's frame-duration maths.
CALIBRATION_ELEMENT = "resolutions"


@dataclass(frozen=True, slots=True)
class StripDeviceSettings:
    """Remove hardware-specific settings so a build is device-neutral.

    A build is one artifact for the whole fleet but is made from a single
    device's capture. `kodi.apply_device_config` only overlays a device's own
    `vars.kodi`, so without this a device with none keeps the captured
    device's panel calibration and audio routing.

    **PARAMETERS:**
        `settings` (Sequence[str]): Setting ids to remove from `guisettings.xml`. Removing the element entirely is what makes Kodi fall back to its own detection.  <br>
        `drop_calibration` (bool): Remove the `<resolutions>` calibration block.  <br>
    """

    settings: Sequence[str] = field(default_factory=lambda: DEVICE_SETTINGS)
    drop_calibration: bool = True

    @property
    def name(self) -> str:
        """RETURNS: str: Short identifier for logs and audit records."""
        return "strip_device_settings"

    def apply(self, profile: Path, config: Mapping[str, Any]) -> list[str]:
        """Remove device-specific settings from the profile's GUI settings.

        **PARAMETERS:**
            `profile` (Path): Extracted profile directory.  <br>
            `config` (Mapping[str, Any]): May supply `settings` and `drop_calibration`, overriding this instance's defaults.  <br>

        **RETURNS:**
            `list[str]`: One description per removal. Empty when the file is absent or unparseable — a profile without GUI settings is not an error, and a build must not fail on one.  <br>
        """
        targets = {str(name) for name in config.get("settings", self.settings)}
        drop_calibration = bool(config.get("drop_calibration", self.drop_calibration))

        path = profile / "userdata" / GUI_SETTINGS
        if not path.is_file():
            return []

        try:
            tree = ElementTree.parse(path)
        except ElementTree.ParseError as exc:
            LOGGER.warning("Could not parse %s, leaving it alone: %s", GUI_SETTINGS, exc)
            return []

        root = tree.getroot()
        changes: list[str] = []

        # Settings can be nested under <section>/<category> groupings, so walk
        # every parent rather than assuming they sit at the top level.
        for parent in root.iter():
            for element in list(parent.findall("setting")):
                if element.get("id") in targets:
                    parent.remove(element)
                    changes.append(f"{GUI_SETTINGS}: removed {element.get('id')}")

        if drop_calibration:
            for parent in root.iter():
                for block in list(parent.findall(CALIBRATION_ELEMENT)):
                    count = len(block.findall("resolution"))
                    parent.remove(block)
                    changes.append(f"{GUI_SETTINGS}: removed display calibration ({count} resolution block(s))")

        if changes:
            tree.write(path, encoding="utf-8", xml_declaration=True)
        return changes
