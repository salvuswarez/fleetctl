"""Starting Kodi on a device.

Android has no supported way to run an application at boot without an app
holding a `BOOT_COMPLETED` receiver, and Kodi declares no `HOME` activity, so
it cannot be made the launcher either. This step is the honest alternative:
something outside the device — a home-automation trigger reacting to the
device coming online — asks fleetctl to bring Kodi up.

The step names no activity and no package manager. It asks the resolved app
manager to launch Kodi's platform identifier, and the device pack works out
what that means for its own platform.
"""

from __future__ import annotations

import logging

from ...core.effects import Capability, Effect
from ...core.workflow.step import DeviceStepContext, StepResult, StepSpec
from .spec import state_spec

LOGGER = logging.getLogger(__name__)

LAUNCH = StepSpec(
    id="kodi.launch",
    summary="Bring Kodi to the foreground on a device, starting it if needed.",
    # Starts a process and changes what is on screen; it destroys nothing.
    effect=Effect.MUTATING,
    requires=frozenset({Capability.EXEC, Capability.APPS}),
    scope="device",
)


def launch(context: DeviceStepContext) -> StepResult:
    """Start Kodi, or bring it forward if it is already running.

    **PARAMETERS:**
        `context` (DeviceStepContext): The device and its resolved app manager.  <br>

    **RETURNS:**
        `StepResult`: Names the device and the identifier launched.  <br>

    **RAISES:**
        `FleetError`: If the platform cannot launch an application this way.  <br>
        `TransportError`: If the launch ran but Kodi is not running afterwards.  <br>
    """
    identifier = state_spec().identifier_for(context.state.platform)

    context.handle.log(f"Launching {identifier} on {context.device.id}...")
    context.handle.check_cancelled()
    context.apps.launch(identifier)

    context.handle.log("Kodi is running")
    return StepResult(summary=f"Launched Kodi on {context.device.id}", facts={"identifier": identifier, "launched": True})
