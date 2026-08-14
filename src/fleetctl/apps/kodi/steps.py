"""Kodi's steps: capture, build, deploy."""

from __future__ import annotations

import logging
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from fleetctl.apps.kodi import abi
from fleetctl.apps.kodi.spec import APP_ID, DEFAULT_PROFILE, PROFILE_MEMBERS, state_spec
from fleetctl.core.artifacts.ref import ArtifactRef
from fleetctl.core.artifacts.store import require_kind
from fleetctl.core.effects import Capability, Effect
from fleetctl.core.errors import FleetError
from fleetctl.core.state import AppStateSpec
from fleetctl.core.workflow.step import DeviceStepContext, StepResult, StepSpec, TransformStepContext

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
    recipe = str(context.config.get("profile") or "")

    context.handle.log(f"Building from {ref.wire}" + (f" with the {recipe} profile..." if recipe else "..."))
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
    # Scanned here because the profile is already extracted, so it costs a
    # walk rather than a second download at deploy time.
    machines = abi.profile_machines(profile)
    context.handle.log(f"Binary addons target: {', '.join(machines) or 'no compiled addons'}")

    name = f"build_{_timestamp()}.tar.gz"
    output = context.workspace / name
    members = _pack_flat(profile, output)
    context.handle.log(f"Packed {', '.join(members)}")

    build_ref = ArtifactRef(kind=BUILDS, name=name)
    # The profile is recorded so `deploy` can refuse to send this build to
    # hardware it was not shaped for; the composition root resolved it. The
    # machines are recorded because the profile name alone cannot catch two
    # device types sharing one recipe.
    meta = {"app": APP_ID, "source": ref.wire, "profile": recipe, "machines": ",".join(machines)}
    info = context.artifacts.put(output, build_ref, meta=meta)
    context.handle.log(f"Build ready: {build_ref.wire} ({info.size // 1024}KB)")
    return StepResult(
        summary=f"Built {build_ref.wire}",
        artifacts={"build": build_ref},
        facts={"source": ref.wire, "profile": recipe, "machines": ",".join(machines)},
    )


def deploy(context: DeviceStepContext) -> StepResult:
    """Deploy a built profile to a device.

    **PARAMETERS:**
        `context` (DeviceStepContext): The device, its resolved state manager, and config.  <br>

    **RETURNS:**
        `StepResult`: Names the build that was deployed.  <br>

    **RAISES:**
        `FleetError`: If the named artifact is not a build, the build was shaped for different hardware, or no build for this device's profile exists.  <br>
    """
    wanted = str(context.config.get("profile") or DEFAULT_PROFILE)
    named = context.config.get("build")
    if named:
        ref = require_kind(ArtifactRef.parse(named), BUILDS)
        _require_matching_profile(context, ref, wanted)
    else:
        ref = _latest_for_profile(context, wanted)
    _require_runnable(context, ref)

    context.handle.log(f"Deploying {ref.wire} to {context.device.id}...")
    local = context.artifacts.get(ref, context.workspace / ref.name)

    context.handle.check_cancelled()
    manager = context.state
    manager.restore(state_spec(), local)

    context.handle.log("Profile restored")
    return StepResult(summary=f"Deployed {ref.wire} to {context.device.id}", facts={"build": ref.wire})


def _profile_of(info: Any) -> str:
    """RETURNS: str: The recipe a build was shaped with.

    A build carrying no recorded profile predates per-device profiles, and
    could only have been made with the default: until the profile reached the
    build step, the registered app was constructed with no arguments and no
    caller could name another recipe. Treating it as the default is a fact
    about how it was produced, not a guess.
    """
    return str(info.meta.get("profile") or DEFAULT_PROFILE)


def _require_matching_profile(context: DeviceStepContext, ref: ArtifactRef, wanted: str) -> None:
    """Refuse a build shaped for hardware other than this device's.

    A build is one artifact for the whole fleet, but not every device can run
    every recipe: a `gold` build carries ARM addon binaries an x86 Steam Deck
    cannot execute, and a `deck` build carries that Deck's keymap and SD-card
    sources onto a Fire Stick. Every device resolves to a definite profile and
    every build to one, so this is symmetric — naming a build explicitly does
    not waive it.

    **PARAMETERS:**
        `context` (DeviceStepContext): The device being deployed to.  <br>
        `ref` (ArtifactRef): The build about to be deployed.  <br>
        `wanted` (str): The profile this device needs.  <br>

    **RAISES:**
        `FleetError`: If the build was shaped with a different recipe. Unknown builds pass: `get` reports a missing artifact better than this can.  <br>
    """
    info = next((item for item in context.artifacts.list(BUILDS) if item.ref.name == ref.name), None)
    if info is None:
        return
    built = _profile_of(info)
    if built != wanted:
        raise FleetError(f"{ref.wire} was built with the {built!r} profile but {context.device.id} needs {wanted!r}; build from a capture of this device first")


def _runtime_abis(context: DeviceStepContext) -> str:
    """Resolve what architecture Kodi will actually run as on this device.

    Three sources, most authoritative first:

    1. An explicit `runtime_abis` config value, so an operator can always
       override a wrong or missing answer.
    2. The installed application's own architecture. This is the real
       constraint — a process loads only libraries matching itself.
    3. The device's `abilist`, used when Kodi is not installed yet and the
       package about to be installed is what will settle it. Wider than the
       truth, so it is the last resort rather than the default.

    **RETURNS:**
        `str`: Comma-separated architectures, or ``""`` when nothing answered.  <br>
    """
    explicit = str(context.config.get("runtime_abis") or "")
    if explicit:
        return explicit

    installed = context.apps.installed_abi(state_spec().identifier_for(context.state.platform))
    if installed:
        return installed

    return str(getattr(context.device, "abilist", "") or getattr(context.device, "abi", "") or "")


def _require_runnable(context: DeviceStepContext, ref: ArtifactRef) -> None:
    """Refuse a build whose binary addons this device cannot execute.

    The profile guard catches a build shaped by the wrong *recipe*. This
    catches the case it cannot see: two device types resolving to the same
    recipe with different architectures behind them. Both are needed — a
    matching recipe name is not evidence of a runnable binary.

    Stays silent unless both sides are known. A build predating machine
    recording, or a device whose pack reports no ABI, yields no verdict, and
    an unverifiable claim must not read as a confirmed failure.

    `runtime_abis` is the ABI of the **Kodi process**, not of the hardware.
    The two differ in a way that matters: a 64-bit device usually reports the
    32-bit ABIs too, and runs 32-bit programs happily — but a 64-bit Kodi on
    that same device cannot `dlopen` a 32-bit addon, because a process loads
    only libraries matching its own architecture. Reading the hardware's list
    here would pass a build that Kodi then fails on. Prefer the installed
    package's own ABI; fall back to the hardware list only when Kodi is absent
    and the package about to be installed is what settles it.

    **PARAMETERS:**
        `context` (DeviceStepContext): The device being deployed to.  <br>
        `ref` (ArtifactRef): The build about to be deployed.  <br>

    **RAISES:**
        `FleetError`: If the build needs an architecture the Kodi process cannot load.  <br>
    """
    reported = _runtime_abis(context)
    if not reported:
        return

    info = next((item for item in context.artifacts.list(BUILDS) if item.ref.name == ref.name), None)
    if info is None:
        return
    recorded = str(info.meta.get("machines") or "")
    if not recorded:
        return

    missing = abi.unsupported(tuple(recorded.split(",")), abi.machines_for(reported))
    if missing:
        raise FleetError(
            f"{ref.wire} carries {'/'.join(missing)} binary addons that Kodi on {context.device.id} cannot load (it runs {reported}); install a matching Kodi or build from a capture of this device"
        )


def _latest_for_profile(context: DeviceStepContext, wanted: str) -> ArtifactRef:
    """Pick the newest build shaped for this device.

    A workflow that names no build deploys to a mixed fleet, so "newest
    overall" is the wrong answer: one Steam Deck build published after a gold
    one would otherwise be sent to every Fire Stick.

    **RETURNS:**
        `ArtifactRef`: The newest build whose profile matches.  <br>

    **RAISES:**
        `FleetError`: If no build for this profile exists.  <br>
    """
    # `list` is already newest-first.
    for info in context.artifacts.list(BUILDS):
        if _profile_of(info) == wanted:
            return info.ref
    raise FleetError(f"No build with the {wanted!r} profile that {context.device.id} needs; build one from a capture of this device")


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

    Written as GNU rather than Python's default PAX. A Kodi profile routinely
    exceeds tar's 100-character name field — addon `__pycache__` trees reach
    130+ — and the two formats encode that overflow differently. The busybox
    and toybox `tar` builds shipped on set-top devices read GNU long-name
    entries but not PAX extended headers: given PAX they truncate the name
    mid-path, report `bad header`, and abort partway through the first member.
    Verified on hardware: an identical 133-character path extracts under GNU
    and fails under PAX.

    **RETURNS:**
        `list[str]`: Member names actually included.  <br>
    """
    included: list[str] = []
    with tarfile.open(destination, "w:gz", format=tarfile.GNU_FORMAT) as archive:
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
