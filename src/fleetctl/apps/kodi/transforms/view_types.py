"""Corrections to a skin's compiled view-type routing.

A skin maps a container's content type to a numbered view through boolean
expressions in a compiled includes file. Shipped defaults can render the same
content differently depending on whether it came from the library or a
plugin, which reads as a bug to anyone using the device.

The expressions themselves live in the profile recipe rather than here: they
are skin-version-specific, and a skin update is a config edit rather than a
code change.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ApplyViewTypes:
    """Replace named boolean expressions in a skin's includes file.

    **PARAMETERS:**
        `includes_path` (str): Addons-relative path of the compiled includes file.  <br>
        `expressions` (Mapping[str, str]): Expression name to its replacement value.  <br>
    """

    includes_path: str = ""
    expressions: Mapping[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        """RETURNS: str: Short identifier for logs and audit records."""
        return "apply_view_types"

    def apply(self, profile: Path, config: Mapping[str, Any]) -> list[str]:
        """Rewrite the configured expressions in place.

        **PARAMETERS:**
            `profile` (Path): Extracted profile directory.  <br>
            `config` (Mapping[str, Any]): May supply `includes_path` and `expressions`.  <br>

        **RETURNS:**
            `list[str]`: One description per expression changed. Empty when nothing is configured or the file is absent — a profile using a different skin is not an error.  <br>
        """
        relative = str(config.get("includes_path", self.includes_path))
        expressions = config.get("expressions", self.expressions)
        if not relative or not expressions:
            return []

        path = profile / "addons" / relative
        if not path.is_file():
            LOGGER.debug("Skin includes file absent, skipping: %s", relative)
            return []

        try:
            tree = ElementTree.parse(path)
        except ElementTree.ParseError as exc:
            LOGGER.warning("Could not parse %s, leaving it alone: %s", relative, exc)
            return []

        root = tree.getroot()
        by_name = {element.get("name"): element for element in root.iter("expression")}
        changes: list[str] = []
        for expression_name, value in expressions.items():
            element = by_name.get(expression_name)
            if element is None:
                LOGGER.debug("Expression %s not present in %s", expression_name, relative)
                continue
            collapsed = " ".join(str(value).split())
            if " ".join((element.text or "").split()) != collapsed:
                element.text = collapsed
                changes.append(f"{relative}: {expression_name} updated")

        if changes:
            tree.write(path, encoding="utf-8", xml_declaration=True)
        return changes
