"""Corrections to `advancedsettings.xml`."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

LOGGER = logging.getLogger(__name__)

ADVANCED_SETTINGS = "advancedsettings.xml"


@dataclass(frozen=True, slots=True)
class RemoveThumbnailSubstitution:
    """Drop a path substitution that redirects the thumbnail cache off-device.

    **PARAMETERS:**
        `marker` (str): Substring identifying the substitution to remove, matched case-insensitively against each entry's ``<from>``.  <br>
    """

    marker: str = "thumbnails"

    @property
    def name(self) -> str:
        """RETURNS: str: Short identifier for logs and audit records."""
        return "remove_thumbnail_substitution"

    def apply(self, profile: Path, config: Mapping[str, Any]) -> list[str]:
        """Remove matching substitutions from the profile's advanced settings.

        **PARAMETERS:**
            `profile` (Path): Extracted profile directory.  <br>
            `config` (Mapping[str, Any]): May supply `marker`, overriding the default.  <br>

        **RETURNS:**
            `list[str]`: One description per removed entry. Empty when the file is absent — a profile without advanced settings is normal, not an error.  <br>
        """
        marker = str(config.get("marker", self.marker)).lower()
        path = profile / "userdata" / ADVANCED_SETTINGS
        if not path.is_file():
            return []

        try:
            tree = ElementTree.parse(path)
        except ElementTree.ParseError as exc:
            LOGGER.warning("Could not parse %s, leaving it alone: %s", ADVANCED_SETTINGS, exc)
            return []

        root = tree.getroot()
        changes: list[str] = []
        for block in list(root.findall("pathsubstitution")):
            for entry in list(block.findall("substitute")):
                source = entry.find("from")
                if source is not None and source.text and marker in source.text.lower():
                    block.remove(entry)
                    changes.append(f"{ADVANCED_SETTINGS}: removed substitution for {source.text}")
            # An emptied block is noise; Kodi does not need it and leaving it
            # behind makes the next reader wonder what used to be there.
            if len(block) == 0:
                root.remove(block)

        if changes:
            tree.write(path, encoding="utf-8", xml_declaration=True)
        return changes
