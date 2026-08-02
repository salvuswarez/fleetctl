"""Apply setting overrides to a profile's userdata XML files."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ApplySettings:
    """Set specific setting ids in specific userdata files.

    **PARAMETERS:**
        `overrides` (Mapping[str, Mapping[str, str]]): Userdata-relative file path to ``{setting id: value}``.  <br>
    """

    overrides: Mapping[str, Mapping[str, str]] = field(default_factory=dict)

    @property
    def name(self) -> str:
        """RETURNS: str: Short identifier for logs and audit records."""
        return "apply_settings"

    def apply(self, profile: Path, config: Mapping[str, Any]) -> list[str]:
        """Apply every configured override under `profile/userdata`.

        **PARAMETERS:**
            `profile` (Path): Extracted profile directory.  <br>
            `config` (Mapping[str, Any]): May supply `settings`, overriding this instance's defaults.  <br>

        **RETURNS:**
            `list[str]`: One description per changed setting. A file that does not exist is skipped rather than created — an override is a correction to something Kodi wrote, not a way to invent config.  <br>
        """
        overrides = config.get("settings", self.overrides)
        userdata = profile / "userdata"
        changes: list[str] = []
        for relative, entries in overrides.items():
            path = userdata / relative
            if not path.is_file():
                LOGGER.debug("Settings file absent, skipping: %s", relative)
                continue
            changes.extend(self._apply_file(path, relative, entries))
        return changes

    def _apply_file(self, path: Path, relative: str, entries: Mapping[str, str]) -> list[str]:
        try:
            tree = ElementTree.parse(path)
        except ElementTree.ParseError as exc:
            LOGGER.warning("Could not parse %s, skipping: %s", relative, exc)
            return []

        root = tree.getroot()
        by_id = {element.get("id"): element for element in root.iter("setting")}
        changes: list[str] = []
        for setting_id, value in entries.items():
            element = by_id.get(setting_id)
            if element is None:
                element = ElementTree.SubElement(root, "setting")
                element.set("id", setting_id)
            if (element.text or "") != value:
                element.text = value
                changes.append(f"{relative}: {setting_id} = {value!r}")
        if changes:
            tree.write(path, encoding="utf-8", xml_declaration=True)
        return changes
