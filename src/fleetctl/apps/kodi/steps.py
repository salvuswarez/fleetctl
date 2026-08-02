"""Kodi's steps: capture, build, deploy.

The split is deliberate and structural.

**capture** pulls a device's live profile into a raw artifact. **build**
applies every profile transform once and publishes a deployable artifact.
**deploy** does no shaping at all — it hands an artifact to the device pack
and applies only what genuinely differs per device.

Doing the shaping once in `build` rather than per-device in `deploy` means
identical work is not repeated for every device, and a deploy cannot fail for
reasons that have nothing to do with the device it is deploying to.

Note what is absent from this module: any on-device path, any archive
command, any free-space arithmetic. Those reach the device through the
`state` verb, which the resolved device pack implements.
"""

from __future__ import annotations

import logging
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from ...core.artifacts.ref import ArtifactRef
from ...core.artifacts.store import require_kind
from ...core.effects import Capability, Effect
from ...core.errors import FleetError
from ...core.state import AppStateSpec, StateManager
from ...core.workflow.step import DeviceStepContext, StepResult, StepSpec, TransformStepContext
from .spec import APP_ID, PROFILE_MEMBERS, state_spec

LOGGER = logging.getLogger(__name__)

CAPTURES = "captures"
BUILDS = "builds"

CAPTURE = StepSpec(
    id="kodi.capture",
    summary="Capture a device's live Kodi profile as a raw artifact.",
    effect=Effect.MUTATING,
    requires=frozenset({Capability.EXEC, Capability.FILES, Capability.STATE}),
    scope="device",
)

BUILD = StepSpec(
    id="kodi.build",
    summary="Shape a captured profile into a deployable build.",
    effect=Effect.MUTATING,
    requires=frozenset(),
    scope="transform",
)

DEPLOY = StepSpec(
    id="kodi.deploy",
    summary="Deploy a built Kodi profile to a device.",
    effect=Effect.DESTRUCTIVE,
    requires=frozenset({Capability.EXEC, Capability.FILES, Capability.STATE, Capability.APPS}),
    scope="device",
)


class StateManagerFactory(Protocol):
    """Supplies the state manager for the device a step is targeting.

    Injected rather than imported: this is how an app pack reaches a device
    pack's implementation without knowing which pack it is.
    """

    def __call__(self, context: DeviceStepContext) -> StateManager: ...


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def capture(context: DeviceStepContext, state_for: StateManagerFactory) -> StepResult:
    """Capture a device's Kodi profile and publish it as an artifact.

    **PARAMETERS:**
        `context` (DeviceStepContext): The device, its transport, and resolved config.  <br>
        `state_for` (StateManagerFactory): Resolves the device pack's state manager.  <br>

    **RETURNS:**
        `StepResult`: Carries the published capture under the ``capture`` artifact role.  <br>
    """
    spec = state_spec(exclude=tuple(context.config.get("capture_exclude", state_spec().exclude)))
    manager = state_for(context)

    context.handle.log(f"Capturing {APP_ID} profile from {context.device.id}...")
    context.handle.check_cancelled()

    name = f"{context.device.id}_{_timestamp()}.tar.gz"
    local = context.workspace / name
    manager.snapshot(spec, local)

    context.handle.check_cancelled()
    context.handle.log("Verifying archive integrity...")
    _verify_archive(local)

    ref = ArtifactRef(kind=CAPTURES, name=name)
    info = context.artifacts.put(local, ref, meta={"app": APP_ID, "device_id": context.device.id})
    context.handle.log(f"Captured {info.size // 1024}KB to {ref.wire}")
    return StepResult(summary=f"Captured {ref.wire}", artifacts={"capture": ref})


def build(context: TransformStepContext) -> StepResult:
    """Shape a captured profile into a deployable build.

    Every transform runs here, once. The output archive is flat — the
    profile's members at the root, no wrapping directory — so a device can
    unpack it straight into its state root with no path rewriting.

    **PARAMETERS:**
        `context` (TransformStepContext): The transform chain, artifact store, and resolved config. Carries no transport, so this step cannot touch a device.  <br>

    **RETURNS:**
        `StepResult`: Carries the published build under the ``build`` artifact role.  <br>

    **RAISES:**
        `FleetError`: If no source capture exists, or the archive has no recognizable profile.  <br>
    """
    source = context.config.get("source")
    ref = ArtifactRef.parse(source) if source else context.artifacts.latest(CAPTURES)

    context.handle.log(f"Building from {ref.wire}...")
    local = context.artifacts.get(ref, context.workspace / ref.name)

    extracted = context.workspace / "profile"
    with tarfile.open(local, "r:gz") as archive:
        archive.extractall(extracted, filter="data")
    profile = _find_profile(extracted)

    for transform in context.transforms:
        context.handle.check_cancelled()
        context.handle.log(f"Applying {transform.name}...")
        for change in transform.apply(profile, dict(context.config.get(transform.name, {}))):
            context.handle.log(f"  {change}")

    context.handle.check_cancelled()
    name = f"build_{_timestamp()}.tar.gz"
    output = context.workspace / name
    members = _pack_flat(profile, output)
    context.handle.log(f"Packed {', '.join(members)}")

    build_ref = ArtifactRef(kind=BUILDS, name=name)
    info = context.artifacts.put(output, build_ref, meta={"app": APP_ID, "source": ref.wire})
    context.handle.log(f"Build ready: {build_ref.wire} ({info.size // 1024}KB)")
    return StepResult(summary=f"Built {build_ref.wire}", artifacts={"build": build_ref}, facts={"source": ref.wire})


def deploy(context: DeviceStepContext, state_for: StateManagerFactory) -> StepResult:
    """Deploy a built profile to a device.

    Does no shaping. What remains here is only what genuinely varies per
    device: which build to send, and the device's own overrides.

    **PARAMETERS:**
        `context` (DeviceStepContext): The device, its transport, and resolved config.  <br>
        `state_for` (StateManagerFactory): Resolves the device pack's state manager.  <br>

    **RETURNS:**
        `StepResult`: Names the build that was deployed.  <br>

    **RAISES:**
        `FleetError`: If the named artifact is not a build, or no build exists.  <br>
    """
    named = context.config.get("build")
    ref = require_kind(ArtifactRef.parse(named), BUILDS) if named else context.artifacts.latest(BUILDS)

    context.handle.log(f"Deploying {ref.wire} to {context.device.id}...")
    local = context.artifacts.get(ref, context.workspace / ref.name)

    context.handle.check_cancelled()
    manager = state_for(context)
    manager.restore(state_spec(), local)

    context.handle.log("Profile restored")
    return StepResult(summary=f"Deployed {ref.wire} to {context.device.id}", facts={"build": ref.wire})


def _find_profile(extracted: Path) -> Path:
    """Locate the profile root inside an extracted archive.

    A capture wraps the profile in its on-device directory name; a build is
    already flat. Accepting both means a build can be rebuilt from its own
    output without a special case.

    **RAISES:**
        `FleetError`: If no directory containing profile members is found.  <br>
    """
    if _looks_like_profile(extracted):
        return extracted
    candidates = [entry for entry in extracted.iterdir() if entry.is_dir() and _looks_like_profile(entry)]
    if not candidates:
        raise FleetError(f"No Kodi profile found in {extracted.name}")
    return candidates[0]


def _looks_like_profile(path: Path) -> bool:
    return any((path / member).is_dir() for member in PROFILE_MEMBERS)


def _pack_flat(profile: Path, destination: Path) -> list[str]:
    """Write the profile's members to a flat gzipped tar.

    Flat means `addons/...` rather than `.kodi/addons/...`, so the device
    extracts straight into its state root.

    **RETURNS:**
        `list[str]`: Member names actually included.  <br>
    """
    included: list[str] = []
    with tarfile.open(destination, "w:gz") as archive:
        for member in PROFILE_MEMBERS:
            path = profile / member
            if path.is_dir():
                archive.add(path, arcname=member)
                included.append(member)
    return included


def _verify_archive(path: Path) -> None:
    """Fail loudly if an archive is truncated or corrupt.

    A capture that raises no error can still produce a truncated archive.
    The predecessor did not check, so a bad archive was published as if it
    were good and only surfaced much later, on an unrelated device's deploy.

    **RAISES:**
        `FleetError`: If the archive cannot be fully read.  <br>
    """
    try:
        with tarfile.open(path, "r:gz") as archive:
            while archive.next() is not None:
                pass
    except (OSError, tarfile.TarError, EOFError) as exc:
        raise FleetError(f"Captured archive is truncated or corrupt: {exc}") from exc


def state_spec_for(config: Mapping[str, Any]) -> AppStateSpec:
    """RETURNS: AppStateSpec: Kodi's state spec, honouring any configured exclusions."""
    return state_spec(exclude=tuple(config.get("capture_exclude", state_spec().exclude)))
