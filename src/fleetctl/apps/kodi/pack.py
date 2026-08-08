"""The Kodi app pack: its steps and its transform chain."""

from __future__ import annotations

import logging
from functools import cached_property
from importlib import resources
from typing import Any, Mapping

import yaml

from ...core.errors import FleetError
from ...core.registry import RegisteredStep
from ...core.workflow.step import ProfileTransform
from ...core.workflow.workflow import Workflow
from . import base_image, caches, device_config, health, steps
from .merging import deep_merge
from .spec import APP_ID
from .transforms.addons import PruneAddons
from .transforms.advanced import RemoveThumbnailSubstitution
from .transforms.device_settings import DEVICE_SETTINGS, StripDeviceSettings
from .transforms.files import ShipFiles
from .transforms.hub_layout import DEFAULT_LAYOUT, ApplyHubLayout
from .transforms.settings import ApplySettings
from .transforms.sources import AddVideoSources
from .transforms.view_types import ApplyViewTypes

LOGGER = logging.getLogger(__name__)

DEFAULT_PROFILE = "gold"


def _read_profile(name: str) -> dict[str, Any]:
    """RETURNS: dict[str, Any]: One profile recipe file, unresolved."""
    text = resources.files(f"fleetctl.apps.{APP_ID}.data.profiles").joinpath(f"{name}.yml").read_text(encoding="utf-8")
    loaded = yaml.safe_load(text)
    return loaded if isinstance(loaded, dict) else {}


def _load_profile(name: str, *, _seen: tuple[str, ...] = ()) -> dict[str, Any]:
    """Load a profile recipe, resolving an `extends:` chain.

    **PARAMETERS:**
        `name` (str): Profile stem, e.g. ``gold``.  <br>
        `_seen` (tuple[str, ...]): Profiles already being resolved, used to detect a cycle.  <br>

    **RETURNS:**
        `dict[str, Any]`: The recipe with any parent layered underneath it. The `extends` key itself is not part of the result.  <br>

    **RAISES:**
        `FleetError`: If the `extends` chain contains a cycle.  <br>
    """
    if name in _seen:
        raise FleetError(f"Profile {name!r} extends itself: {' -> '.join([*_seen, name])}")

    recipe = _read_profile(name)
    parent = recipe.pop("extends", None)
    if not parent:
        return recipe
    return deep_merge(_load_profile(str(parent), _seen=(*_seen, name)), recipe)


class KodiApp:
    """Kodi profile management.

    **PARAMETERS:**
        `profile` (str): Which shipped recipe to use. Defaults to ``gold``.  <br>
        `overrides` (Mapping[str, Any] | None): Replaces the shipped recipe entirely. Defaults to ``None``.  <br>
    """

    id = APP_ID

    def __init__(self, profile: str = DEFAULT_PROFILE, overrides: Mapping[str, Any] | None = None) -> None:
        self._profile = profile
        self._overrides = dict(overrides) if overrides is not None else None

    @cached_property
    def recipe(self) -> dict[str, Any]:
        """RETURNS: dict[str, Any]: The resolved profile recipe."""
        return self._overrides if self._overrides is not None else _load_profile(self._profile)

    @cached_property
    def transforms(self) -> tuple[ProfileTransform, ...]:
        """Build the transform chain from the recipe.

        **RETURNS:**
            `tuple[ProfileTransform, ...]`: The chain, in application order.  <br>
        """
        prune = self.recipe.get("prune_addons", {})
        settings = self.recipe.get("apply_settings", {})
        views = self.recipe.get("apply_view_types", {})
        thumbnails = self.recipe.get("remove_thumbnail_substitution")
        hubs = self.recipe.get("apply_hub_layout")
        strip = self.recipe.get("strip_device_settings", {})
        chain: list[ProfileTransform] = [
            PruneAddons(allow=tuple(prune.get("allow", ())), allow_prefixes=tuple(prune.get("allow_prefixes", ()))),
            # Before ApplySettings, so a recipe that deliberately pins one of
            # these keys still wins. Unconditional: a build is shared by the
            # whole fleet, so carrying one device's calibration is never right.
            StripDeviceSettings(
                settings=tuple(strip.get("settings", DEVICE_SETTINGS)),
                drop_calibration=bool(strip.get("drop_calibration", True)),
            ),
            ApplySettings(overrides=settings.get("settings", {})),
        ]
        # Before the file-editing transforms below, so a shipped file can then
        # be adjusted rather than overwriting one they just corrected.
        shipped = self.recipe.get("ship_files") or {}
        if shipped.get("files"):
            chain.insert(2, ShipFiles(files=dict(shipped["files"])))

        video_sources = self.recipe.get("add_video_sources") or {}
        if video_sources.get("sources"):
            chain.append(AddVideoSources(sources=tuple(video_sources["sources"])))
        if thumbnails is not None:
            chain.append(RemoveThumbnailSubstitution())
        if views:
            chain.append(ApplyViewTypes(includes_path=str(views.get("includes_path", "")), expressions=views.get("expressions", {})))
        if hubs is not None:
            chain.append(ApplyHubLayout(layout=str(hubs.get("layout", DEFAULT_LAYOUT))))
        return tuple(chain)

    def workflows(self) -> list[Workflow]:
        """RETURNS: list[Workflow]: Workflows shipped with this app."""
        directory = resources.files(f"fleetctl.apps.{APP_ID}.data.workflows")
        found: list[Workflow] = []
        for entry in directory.iterdir():
            if entry.name.endswith(".yml"):
                found.append(Workflow.from_yaml(entry.read_text(encoding="utf-8"), source=entry.name))
        return found

    def steps(self) -> list[RegisteredStep]:
        """RETURNS: list[RegisteredStep]: The capture, build, and deploy steps."""
        return [
            RegisteredStep(spec=steps.CAPTURE, run=steps.capture, provider=APP_ID),
            RegisteredStep(spec=steps.BUILD, run=steps.build, provider=APP_ID),
            RegisteredStep(spec=steps.DEPLOY, run=steps.deploy, provider=APP_ID),
            RegisteredStep(spec=base_image.FETCH_BASE, run=base_image.fetch_base, provider=APP_ID),
            RegisteredStep(spec=base_image.CHECK_UPDATE, run=base_image.check_update, provider=APP_ID),
            RegisteredStep(spec=base_image.INSTALL_BASE, run=base_image.install_base, provider=APP_ID),
            RegisteredStep(spec=device_config.APPLY_DEVICE_CONFIG, run=device_config.apply_device_config, provider=APP_ID),
            RegisteredStep(spec=device_config.READ_DISPLAY, run=device_config.read_display, provider=APP_ID),
            RegisteredStep(spec=health.CHECK, run=health.check, provider=APP_ID),
            RegisteredStep(spec=caches.TRIM_CACHES, run=caches.trim_caches, provider=APP_ID),
        ]
