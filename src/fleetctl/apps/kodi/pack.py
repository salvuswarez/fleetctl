"""The Kodi app pack: its steps and its transform chain."""

from __future__ import annotations

import logging
from functools import cached_property
from importlib import resources
from typing import Any, Mapping

import yaml

from ...core.registry import RegisteredStep
from ...core.workflow.step import ProfileTransform
from . import steps
from .spec import APP_ID
from .transforms.addons import PruneAddons
from .transforms.settings import ApplySettings

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

        Order matters: addons are pruned first, so settings overrides are not
        applied to files that are about to be deleted.

        **RETURNS:**
            `tuple[ProfileTransform, ...]`: The chain, in application order.  <br>
        """
        prune = self.recipe.get("prune_addons", {})
        settings = self.recipe.get("apply_settings", {})
        return (
            PruneAddons(allow=tuple(prune.get("allow", ())), allow_prefixes=tuple(prune.get("allow_prefixes", ()))),
            ApplySettings(overrides=settings.get("settings", {})),
        )

    def steps(self) -> list[RegisteredStep]:
        """RETURNS: list[RegisteredStep]: The capture, build, and deploy steps."""
        return [
            RegisteredStep(spec=steps.CAPTURE, run=steps.capture, provider=APP_ID),
            RegisteredStep(spec=steps.BUILD, run=steps.build, provider=APP_ID),
            RegisteredStep(spec=steps.DEPLOY, run=steps.deploy, provider=APP_ID),
        ]
