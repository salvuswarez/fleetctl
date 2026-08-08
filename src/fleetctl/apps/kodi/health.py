"""What a device reports about its own Kodi install."""

from __future__ import annotations

import logging
import posixpath
import re
import shlex

from ...core.effects import Capability, Effect
from ...core.workflow.step import DeviceStepContext, StepResult, StepSpec
from .spec import state_spec

LOGGER = logging.getLogger(__name__)

SKIN_ID = "skin.arctic.fuse.3"
_ADDON_VERSION = re.compile(r'<addon\b[^>]*\bversion="([^"]+)"')

CHECK = StepSpec(
    id="kodi.check",
    summary="Report the installed Kodi and skin versions.",
    effect=Effect.READ,
    requires=frozenset({Capability.EXEC, Capability.STATE, Capability.APPS}),
    scope="device",
)


def check(context: DeviceStepContext) -> StepResult:
    """Read the Kodi and Arctic Fuse versions a device is running.

    **PARAMETERS:**
        `context` (DeviceStepContext): The device, its transport, and its app and state managers.  <br>

    **RETURNS:**
        `StepResult`: Facts carry `kodi_version` and `arctic_fuse` where the device answered.  <br>
    """
    facts: dict[str, str] = {}

    # The identifier differs per platform -- `org.xbmc.kodi` on Android,
    # `tv.kodi.Kodi` under Flatpak. Asking the state manager which platform it
    # serves is what keeps this from reporting "not installed" on a Steam Deck
    # running Kodi perfectly well.
    kodi_version = context.apps.installed_version(state_spec().identifier_for(context.state.platform))
    if kodi_version:
        facts["kodi_version"] = kodi_version

    skin = skin_version(context)
    if skin:
        facts["arctic_fuse"] = skin

    context.handle.log(", ".join(f"{key}={value}" for key, value in sorted(facts.items())) or "no Kodi install found")
    return StepResult(summary=f"{context.device.id}: {facts.get('kodi_version', 'Kodi not installed')}", facts=dict(facts))


def skin_version(context: DeviceStepContext) -> str:
    """RETURNS: str: The Arctic Fuse version from its `addon.xml`, or ``""`` when the skin is absent."""
    path = posixpath.join(context.state.state_root(state_spec()), "addons", SKIN_ID, "addon.xml")
    xml = context.transport.exec_ok(f"cat {shlex.quote(path)}", effect=Effect.READ)
    match = _ADDON_VERSION.search(xml)
    return match.group(1) if match else ""
