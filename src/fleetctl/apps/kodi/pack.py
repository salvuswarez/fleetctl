"""The Kodi app pack: its steps and its transform chain."""

from __future__ import annotations

import logging
from functools import cached_property
from importlib import resources
from typing import Any, Mapping

import yaml

from ...core.registry import RegisteredStep
from ...core.workflow.step import ProfileTransform
from ...core.workflow.workflow import Workflow
from . import base_image, device_config, health, steps
from .spec import APP_ID
from .transforms.addons import PruneAddons
from .transforms.advanced import RemoveThumbnailSubstitution
from .transforms.hub_layout import DEFAULT_LAYOUT, ApplyHubLayout
from .transforms.settings import ApplySettings
from .transforms.view_types import ApplyViewTypes

LOGGER = logging.getLogger(__name__)

DEFAULT_PROFILE = "gold"


def _load_profile(name: str) -> dict[str, Any]:
    """RETURNS: dict[str, Any]: A profile recipe shipped with this pack."""
    text = resources.files(f"fleetctl.apps.{APP_ID}.data.profiles").joinpath(f"{name}.yml").read_text(encoding="utf-8")
    loaded = yaml.safe_load(text)
    return loaded if isinstance(loaded, dict) else {}


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
        chain: list[ProfileTransform] = [
            PruneAddons(allow=tuple(prune.get("allow", ())), allow_prefixes=tuple(prune.get("allow_prefixes", ()))),
            ApplySettings(overrides=settings.get("settings", {})),
        ]
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
        ]
