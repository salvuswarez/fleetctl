"""Generate a skin's home-screen hubs from one layout definition."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from fleetctl.apps.kodi.merging import deep_merge
from fleetctl.core.errors import FleetError

LOGGER = logging.getLogger(__name__)

DEFAULT_LAYOUT = "arctic-fuse-3"

_TMDB = "plugin://plugin.video.themoviedb.helper/"
# Opens a node file as a folder. Verified against TMDbHelper 6.18's
# `basedir_nodes.py`: `filename` is resolved inside the addon's nodes dir.
_OPEN_NODE = _TMDB + "?info=dir_custom_node&filename={filename}"
# Separates a hub's node from the per-group nodes it links to, so a build can
# remove the group nodes it wrote last time without touching anyone else's.
_GROUP_NODE_SEP = "--"
_NODES_REL = "addon_data/plugin.video.themoviedb.helper/nodes"
_SKINVARS_REL = "addon_data/script.skinvariables/nodes/skin.arctic.fuse.3"


def _read_layout(name: str) -> dict[str, Any]:
    """RETURNS: dict[str, Any]: One layout file, unresolved."""
    text = resources.files("fleetctl.apps.kodi.data.hubs").joinpath(f"{name}.yml").read_text(encoding="utf-8")
    loaded = yaml.safe_load(text)
    return loaded if isinstance(loaded, dict) else {}


def load_layout(name: str = DEFAULT_LAYOUT, *, _seen: tuple[str, ...] = ()) -> dict[str, Any]:
    """Load a layout, resolving `extends:` and `add_widgets:`.

    A layout is shared by the whole fleet, so a device that needs one extra row
    — a local folder only it has — declares a variant rather than editing the
    shared file. `add_widgets` appends, because a plain merge replaces a list
    and would mean restating a hub's every row to add one.

    **PARAMETERS:**
        `name` (str): Layout stem, e.g. ``arctic-fuse-3``.  <br>
        `_seen` (tuple[str, ...]): Layouts already being resolved, used to detect a cycle.  <br>

    **RETURNS:**
        `dict[str, Any]`: The resolved layout. `extends` and `add_widgets` are not part of the result.  <br>

    **RAISES:**
        `FleetError`: If the `extends` chain contains a cycle, or `add_widgets` names a hub the layout does not define.  <br>
    """
    if name in _seen:
        raise FleetError(f"Layout {name!r} extends itself: {' -> '.join([*_seen, name])}")

    definition = _read_layout(name)
    parent = definition.pop("extends", None)
    additions = definition.pop("add_widgets", None) or {}
    resolved = deep_merge(load_layout(str(parent), _seen=(*_seen, name)), definition) if parent else definition

    if additions:
        hubs = {slot: dict(spec) for slot, spec in (resolved.get("hubs") or {}).items()}
        for slot, rows in additions.items():
            hub = hubs.get(str(slot))
            if hub is None:
                raise FleetError(f"Layout {name!r} adds widgets to unknown hub {slot!r}")
            hub["widgets"] = [*(hub.get("widgets") or []), *rows]
        resolved["hubs"] = hubs
    return resolved


def _guid(*parts: str) -> str:
    """Derive a stable id from `parts`.

    Deterministic rather than random so regenerating an unchanged hub yields
    a byte-identical file, and the build's hash comparison does not re-push it.

    **RETURNS:**
        `str`: A `guid-xxxxxxxx` identifier.  <br>
    """
    return "guid-" + hashlib.md5("|".join(parts).encode()).hexdigest()[:8]


def _path(row: Mapping[str, Any]) -> str:
    """Compose a row's path.

    `tmdb` names any TMDbHelper list route (`trending_week`, `airing_today`)
    with its params; `discover` is the common case of the `discover` route,
    which also needs `with_id`.

    **RETURNS:**
        `str`: The row's literal `path`, or one composed from its `tmdb` or `discover` params.  <br>
    """
    literal = row.get("path")
    if literal:
        return str(literal)
    if row.get("tmdb"):
        listing = dict(row["tmdb"])
        info = listing.pop("info")
        params = "".join(f"&{key}={value}" for key, value in listing.items())
        return f"{_TMDB}?info={info}{params}&widget=True"
    discover = dict(row.get("discover") or {})
    tmdb_type = discover.pop("tmdb_type", "movie")
    params = "&".join(f"{key}={value}" for key, value in discover.items())
    return f"{_TMDB}?info=discover&with_id=True&tmdb_type={tmdb_type}&{params}&widget=True"


def _rows(rows: Sequence[Mapping[str, Any]], icons: Mapping[str, str], scope: str) -> list[dict[str, Any]]:
    """RETURNS: list[dict[str, Any]]: Rows with icons resolved, paths composed, styles carried, and guids assigned."""
    return [_row(row, icons, scope) for row in rows]


def _row(row: Mapping[str, Any], icons: Mapping[str, str], scope: str) -> dict[str, Any]:
    """RETURNS: dict[str, Any]: One row as skinvariables stores it; `widget_style` only when the layout sets one, so the skin default still applies otherwise."""
    entry: dict[str, Any] = {
        "label": str(row["label"]),
        "path": _path(row),
        "icon": str(row.get("icon", "")).format(**icons),
        "target": "videos",
        "guid": _guid(scope, str(row["label"])),
    }
    if row.get("style"):
        entry["widget_style"] = str(row["style"])
    return entry


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
            rows = spec.get("widgets") or []
            widgets = _rows(rows, icons, str(slot))
            _write_json(skinvars / f"skinvariables-shortcut-{slot}widgets.json", widgets)
            written.append(f"{slot}: {len(widgets)} widget row(s)")

            groups = spec.get("submenu") or []
            # `submenu: []` means "this hub has none", and is written as such:
            # skipping the file left a captured profile's old one in place, so
            # Discover kept Browse's four duplicate menus after a deploy. No key
            # at all means the skin owns the file (Home's Videos/Music/Pictures).
            if "submenu" in spec:
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

            group_files = self._write_group_nodes(nodes, spec, groups, icons)
            _write_json(nodes / str(spec["node"]), self._node(spec, widgets, groups, group_files, icons))

        return written

    def _write_group_nodes(self, nodes: Path, spec: Mapping[str, Any], groups: Sequence[Mapping[str, Any]], icons: Mapping[str, str]) -> list[str]:
        """Write one node per sub-tab group, so the hub page can open the whole group.

        The hub page used to link each group to its *first row*: "Genres" opened
        Action & Adventure, "By Network" opened Netflix. A group needs a folder
        of its own to land in, and a TMDbHelper node is that folder.

        Group nodes from the previous build are removed first, so a renamed or
        dropped group does not linger in TMDbHelper's node list.

        **RETURNS:**
            `list[str]`: The file written for each group, in order, or ``""`` for a group with no rows.  <br>

        **RAISES:**
            `FleetError`: If two groups on one hub would write the same node file.  <br>
        """
        stem = Path(str(spec["node"])).stem
        slugs = [_slug(str(group["label"])) for group in groups]
        clashes = sorted({slug for slug in slugs if slugs.count(slug) > 1})
        if clashes:
            raise FleetError(f"Hub {spec.get('node_name', stem)} has two groups that would share a node file: {', '.join(clashes)}")
        for stale in nodes.glob(f"{stem}{_GROUP_NODE_SEP}*.json"):
            stale.unlink()

        files: list[str] = []
        for group in groups:
            rows = group.get("rows") or []
            if not rows:
                files.append("")
                continue
            filename = f"{stem}{_GROUP_NODE_SEP}{_slug(str(group['label']))}.json"
            entries = [{"name": row["label"], "icon": row["icon"], "path": row["path"], "widget": "False"} for row in _rows(rows, icons, filename)]
            _write_json(nodes / filename, {"name": str(group["label"]), "icon": str(group.get("icon", "")).format(**icons), "list": entries})
            files.append(filename)
        return files

    def _node(
        self,
        spec: Mapping[str, Any],
        widgets: Sequence[Mapping[str, Any]],
        groups: Sequence[Mapping[str, Any]],
        group_files: Sequence[str],
        icons: Mapping[str, str],
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
        for group, filename in zip(groups, group_files):
            if filename:
                path = _OPEN_NODE.format(filename=filename)
                entries.append({"name": str(group["label"]), "icon": str(group.get("icon", "")).format(**icons), "path": path, "widget": "False"})
        return {"name": str(spec["node_name"]), "icon": f"{icons.get('tmdb', '')}/discover.png", "list": entries}


def _slug(label: str) -> str:
    """RETURNS: str: `label` lowercased with every run of non-alphanumerics collapsed to one hyphen, safe in a URL and a filename."""
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=4), encoding="utf-8")
