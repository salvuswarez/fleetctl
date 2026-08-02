"""Prune a profile's addons down to an allow-list."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class PruneAddons:
    """Remove every addon folder not covered by the allow-list.

    Prefixes cover dependency and engine categories — libraries and services
    other addons rely on, never a standalone content source — so a build does
    not have to enumerate every transitive dependency by name.

    **PARAMETERS:**
        `allow` (Sequence[str]): Exact addon ids to keep.  <br>
        `allow_prefixes` (Sequence[str]): Id prefixes to keep.  <br>
    """

    allow: Sequence[str] = field(default_factory=tuple)
    allow_prefixes: Sequence[str] = field(default_factory=tuple)

    @property
    def name(self) -> str:
        """RETURNS: str: Short identifier for logs and audit records."""
        return "prune_addons"

    def apply(self, profile: Path, config: Mapping[str, Any]) -> list[str]:
        """Remove non-allowed addon folders from `profile/addons`.

        **PARAMETERS:**
            `profile` (Path): Extracted profile directory.  <br>
            `config` (Mapping[str, Any]): May supply `allow` and `allow_prefixes`, overriding this instance's defaults.  <br>

        **RETURNS:**
            `list[str]`: One description per removed addon. Empty when the addons directory is absent — a profile without one is not an error.  <br>
        """
        addons = profile / "addons"
        if not addons.is_dir():
            return []

        allow = set(config.get("allow", self.allow))
        prefixes = tuple(config.get("allow_prefixes", self.allow_prefixes))

        removed: list[str] = []
        for entry in sorted(addons.iterdir()):
            if not entry.is_dir() or entry.name in allow or entry.name.startswith(prefixes):
                continue
            shutil.rmtree(entry)
            removed.append(f"removed addon {entry.name}")
        return removed
