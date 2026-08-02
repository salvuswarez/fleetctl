"""Kodi's steps: capture, build, deploy."""

from __future__ import annotations

import logging
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ...core.artifacts.ref import ArtifactRef
from ...core.artifacts.store import require_kind
from ...core.effects import Capability, Effect
from ...core.errors import FleetError
from ...core.state import AppStateSpec
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


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def capture(context: DeviceStepContext) -> StepResult:
    """Capture a device's Kodi profile and publish it as an artifact.

    **PARAMETERS:**
        `context` (DeviceStepContext): The device, its resolved state manager, and config.  <br>

    **RETURNS:**
        `StepResult`: Carries the published capture under the ``capture`` artifact role.  <br>
    """
    spec = state_spec(exclude=tuple(context.config.get("capture_exclude", state_spec().exclude)))
    manager = context.state

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


def deploy(context: DeviceStepContext) -> StepResult:
    """Deploy a built profile to a device.

    **PARAMETERS:**
        `context` (DeviceStepContext): The device, its resolved state manager, and config.  <br>

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
    manager = context.state
    manager.restore(state_spec(), local)

    context.handle.log("Profile restored")
    return StepResult(summary=f"Deployed {ref.wire} to {context.device.id}", facts={"build": ref.wire})


def _find_profile(extracted: Path) -> Path:
    """Locate the profile root inside an extracted archive.

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
