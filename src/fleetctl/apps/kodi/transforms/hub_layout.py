"""Generate a skin's home-screen hubs from one layout definition."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

LOGGER = logging.getLogger(__name__)

DEFAULT_LAYOUT = "arctic-fuse-3"

_TMDB = "plugin://plugin.video.themoviedb.helper/"
_NODES_REL = "addon_data/plugin.video.themoviedb.helper/nodes"
_SKINVARS_REL = "addon_data/script.skinvariables/nodes/skin.arctic.fuse.3"


def load_layout(name: str = DEFAULT_LAYOUT) -> dict[str, Any]:
    """RETURNS: dict[str, Any]: A layout definition shipped with this pack."""
    text = resources.files("fleetctl.apps.kodi.data.hubs").joinpath(f"{name}.yml").read_text(encoding="utf-8")
    loaded = yaml.safe_load(text)
    return loaded if isinstance(loaded, dict) else {}


def _guid(*parts: str) -> str:
    """Derive a stable id from `parts`.

    Deterministic rather than random so regenerating an unchanged hub yields
    a byte-identical file, and the build's hash comparison does not re-push it.

    **RETURNS:**
        `str`: A `guid-xxxxxxxx` identifier.  <br>
    """
    return "guid-" + hashlib.md5("|".join(parts).encode()).hexdigest()[:8]


def _path(row: Mapping[str, Any]) -> str:
    """RETURNS: str: The row's literal `path`, or one composed from its `discover` params."""
    literal = row.get("path")
    if literal:
        return str(literal)
    discover = dict(row.get("discover") or {})
    tmdb_type = discover.pop("tmdb_type", "movie")
    params = "&".join(f"{key}={value}" for key, value in discover.items())
    return f"{_TMDB}?info=discover&with_id=True&tmdb_type={tmdb_type}&{params}&widget=True"


def _rows(rows: Sequence[Mapping[str, Any]], icons: Mapping[str, str], scope: str) -> list[dict[str, Any]]:
    """RETURNS: list[dict[str, Any]]: Rows with icons resolved, paths composed, and guids assigned."""
    return [
        {
            "label": str(row["label"]),
            "path": _path(row),
            "icon": str(row.get("icon", "")).format(**icons),
            "target": "videos",
            "guid": _guid(scope, str(row["label"])),
        }
        for row in rows
    ]


def _blank_slot() -> dict[str, Any]:
    """RETURNS: dict[str, Any]: The empty trailing entry the skin's own editor keeps as an "add item" affordance."""
    return {"label": "", "icon": "", "path": "", "target": "", "submenu": [], "widgets": [], "guid": _guid("blank")}


@dataclass(frozen=True, slots=True)
class ApplyHubLayout:
    """Write the skinvariables and TMDbHelper JSON for every managed hub.

    The two live in different addons and drift apart when edited by hand: a
    captured profile listed seven rows for Movies as a node but four as
    widgets, so browsing into a hub showed different content than its home
    rows. Both are generated here from one definition.

    **PARAMETERS:**
        `layout` (str): Name of a layout shipped under `data/hubs`. Defaults to ``arctic-fuse-3``.  <br>
    """

    layout: str = DEFAULT_LAYOUT

    @property
    def name(self) -> str:
        """RETURNS: str: Short identifier for logs and audit records."""
        return "apply_hub_layout"

    def apply(self, profile: Path, config: Mapping[str, Any]) -> list[str]:
        """Regenerate widget, submenu, and node files for the managed hubs.

        **PARAMETERS:**
            `profile` (Path): Extracted profile directory, mutated in place. Hubs absent from the layout are never read or written.  <br>
            `config` (Mapping[str, Any]): May supply `layout` to override the shipped default.  <br>

        **RETURNS:**
            `list[str]`: One line per file written.  <br>
        """
        definition = load_layout(str(config.get("layout", self.layout)))
        hubs = definition.get("hubs") or {}
        if not hubs:
            LOGGER.debug("Layout %s defines no hubs", self.layout)
            return []

        icons = definition.get("icons") or {}
        skinvars = profile / "userdata" / _SKINVARS_REL
        nodes = profile / "userdata" / _NODES_REL
        skinvars.mkdir(parents=True, exist_ok=True)
        nodes.mkdir(parents=True, exist_ok=True)

        written: list[str] = []
        for slot, spec in hubs.items():
            widgets = _rows(spec.get("widgets") or [], icons, str(slot))
            _write_json(skinvars / f"skinvariables-shortcut-{slot}widgets.json", widgets)
            written.append(f"{slot}: {len(widgets)} widget row(s)")

            groups = spec.get("submenu") or []
            if groups:
                submenu = [
                    {
                        "label": str(group["label"]),
                        "path": "Custom_Submenu",
                        "icon": str(group.get("icon", "")).format(**icons),
                        "target": "",
                        "guid": _guid(str(slot), "sub", str(group["label"])),
                        "submenu": _rows(group.get("rows") or [], icons, f"{slot}:{group['label']}"),
                    }
                    for group in groups
                ]
                submenu.append(_blank_slot())
                _write_json(skinvars / f"skinvariables-shortcut-{slot}submenu.json", submenu)
                written.append(f"{slot}: {len(submenu) - 1} sub-tab(s)")

            _write_json(nodes / str(spec["node"]), self._node(spec, widgets, groups, icons))

        return written

    def _node(
        self, spec: Mapping[str, Any], widgets: Sequence[Mapping[str, Any]], groups: Sequence[Mapping[str, Any]], icons: Mapping[str, str]
    ) -> dict[str, Any]:
        """Build the TMDbHelper node that mirrors a hub's home rows.

        `widget` is False throughout: this list is the page you land on after
        navigating into the hub, so rows load on select. Auto-loading would
        fire every row's live TMDb query at once, which is how slot 1104
        preceded an OOM kill on a 1.7GB device.

        **RETURNS:**
            `dict[str, Any]`: The node document.  <br>
        """
        entries = [{"name": row["label"], "icon": row["icon"], "path": row["path"], "widget": "False"} for row in widgets]
        for group in groups:
            rows = group.get("rows") or []
            if rows:
                entries.append({"name": str(group["label"]), "icon": str(group.get("icon", "")).format(**icons), "path": _path(rows[0]), "widget": "False"})
        return {"name": str(spec["node_name"]), "icon": f"{icons.get('tmdb', '')}/discover.png", "list": entries}


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=4), encoding="utf-8")
