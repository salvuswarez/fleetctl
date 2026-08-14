"""Add video sources to a profile's `sources.xml`."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from fleetctl.core.errors import FleetError

LOGGER = logging.getLogger(__name__)

SOURCES = "sources.xml"


@dataclass(frozen=True, slots=True)
class AddVideoSources:
    """Merge video sources into whatever `sources.xml` the capture held.

    A merge rather than a shipped file: the captured `sources.xml` carries the
    fleet's own shares, and replacing it wholesale would either drop them or
    require committing their credentials alongside this recipe.

    Sources are added, never scraped. Content type lives in the video database,
    which is shared across the fleet — a device-local path scraped into it
    resolves on no other device.

    **PARAMETERS:**
        `sources` (Sequence[Mapping[str, str]]): Each needs `name` and `path`; `thumbnail` is optional.  <br>
    """

    sources: Sequence[Mapping[str, str]] = field(default_factory=tuple)

    @property
    def name(self) -> str:
        """RETURNS: str: Short identifier for logs and audit records."""
        return "add_video_sources"

    def apply(self, profile: Path, config: Mapping[str, Any]) -> list[str]:
        """Add each configured source to `userdata/sources.xml`.

        **PARAMETERS:**
            `profile` (Path): Extracted profile directory.  <br>
            `config` (Mapping[str, Any]): May supply `sources`, overriding this instance's list.  <br>

        **RETURNS:**
            `list[str]`: One description per source added. Empty when the file is absent or every source is already present.  <br>

        **RAISES:**
            `FleetError`: If a source is missing `name` or `path`.  <br>
        """
        wanted = list(config.get("sources", self.sources))
        if not wanted:
            return []

        path = profile / "userdata" / SOURCES
        if not path.is_file():
            LOGGER.warning("%s is absent from the profile, leaving it alone", SOURCES)
            return []

        try:
            tree = ElementTree.parse(path)
        except ElementTree.ParseError as exc:
            LOGGER.warning("Could not parse %s, leaving it alone: %s", SOURCES, exc)
            return []

        root = tree.getroot()
        video = root.find("video")
        if video is None:
            video = ElementTree.SubElement(root, "video")

        existing = {(source.findtext("path") or "").strip() for source in video.findall("source")}
        changes: list[str] = []
        for entry in wanted:
            label, location = str(entry.get("name", "")), str(entry.get("path", ""))
            if not label or not location:
                raise FleetError(f"add_video_sources entry needs both name and path, got {entry!r}")
            if location in existing:
                continue
            _append(video, label, location, str(entry.get("thumbnail", "")))
            changes.append(f"{SOURCES}: added video source {label}")

        if changes:
            ElementTree.indent(tree, space="    ")
            tree.write(path, encoding="utf-8", xml_declaration=True)
        return changes


def _append(video: ElementTree.Element, label: str, location: str, thumbnail: str) -> None:
    """Append one `<source>` element in the shape Kodi writes."""
    source = ElementTree.SubElement(video, "source")
    ElementTree.SubElement(source, "name").text = label
    path_element = ElementTree.SubElement(source, "path")
    path_element.set("pathversion", "1")
    path_element.text = location
    if thumbnail:
        thumb = ElementTree.SubElement(source, "thumbnail")
        thumb.set("pathversion", "1")
        thumb.text = thumbnail
    ElementTree.SubElement(source, "allowsharing").text = "true"
