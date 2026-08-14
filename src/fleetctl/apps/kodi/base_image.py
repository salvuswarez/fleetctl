"""The shared Kodi base image: fetching it, and keeping devices on it."""

from __future__ import annotations

import logging
import re
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from fleetctl.apps.kodi.spec import APP_ID, IDENTIFIERS
from fleetctl.core.artifacts.ref import ArtifactRef
from fleetctl.core.effects import Capability, Effect
from fleetctl.core.errors import ArtifactError, FleetError
from fleetctl.core.workflow.step import DeviceStepContext, FleetStepContext, StepResult, StepSpec

LOGGER = logging.getLogger(__name__)

BASE = "base"
MIRROR_URL = "https://mirrors.kodi.tv/releases/android/arm/"
DEFAULT_ARCH = "armeabi-v7a"

# The mirror above serves Android APKs only, so the base image applies to this
# platform and no other.
ANDROID = "android"

# Anything carrying one of these is a pre-release. A fleet should not drift
# onto a nightly because it happened to sort highest.
UNSTABLE_MARKERS = ("beta", "rc", "alpha", "nightly", "dev")

_VERSION = re.compile(r"kodi-(\d+(?:\.\d+)*)")
_DOWNLOAD_TIMEOUT_S = 120.0
_INDEX_TIMEOUT_S = 30.0
_CHUNK = 65536
_USER_AGENT = "fleetctl"

FETCH_BASE = StepSpec(
    id="kodi.fetch_base",
    summary="Download the latest stable Kodi APK and publish it as the fleet's base image.",
    effect=Effect.MUTATING,
    requires=frozenset(),
    scope="fleet",
)

CHECK_UPDATE = StepSpec(
    id="kodi.check_update",
    summary="Compare the published base image against the latest stable Kodi release.",
    effect=Effect.READ,
    requires=frozenset(),
    scope="fleet",
)

INSTALL_BASE = StepSpec(
    id="kodi.install_base",
    summary="Install the published base Kodi APK on a device, if it is not already running it.",
    effect=Effect.DESTRUCTIVE,
    requires=frozenset({Capability.EXEC, Capability.FILES, Capability.APPS}),
    scope="device",
)


def version_key(name: str) -> tuple[int, ...]:
    """RETURNS: tuple[int, ...]: A sortable version tuple parsed from an APK filename, or zeros if it has none."""
    match = _VERSION.search(name)
    if not match:
        return (0, 0, 0)
    parts = [int(piece) for piece in match.group(1).split(".") if piece.isdigit()]
    return tuple((parts + [0, 0, 0])[:3])


def is_stable(name: str) -> bool:
    """RETURNS: bool: Whether an APK filename looks like a stable release."""
    lowered = name.lower()
    return not any(marker in lowered for marker in UNSTABLE_MARKERS)


def parse_index(html: str, arch: str = DEFAULT_ARCH) -> list[str]:
    """Extract stable APK filenames for one architecture from a mirror listing.

    **PARAMETERS:**
        `html` (str): The mirror's directory listing.  <br>
        `arch` (str): Android ABI to match, e.g. ``armeabi-v7a``.  <br>

    **RETURNS:**
        `list[str]`: Stable filenames, newest first.  <br>
    """
    pattern = re.compile(rf'href="(kodi-[\d.]+[^"]*-{re.escape(arch)}\.apk)"')
    names = {match.group(1) for match in pattern.finditer(html) if is_stable(match.group(1))}
    return sorted(names, key=version_key, reverse=True)


def latest_release(arch: str = DEFAULT_ARCH, *, url: str = MIRROR_URL) -> tuple[str, str]:
    """Find the newest stable Kodi APK on the mirror.

    **RETURNS:**
        `tuple[str, str]`: ``(filename, version)``.  <br>

    **RAISES:**
        `FleetError`: If the mirror is unreachable or offers no stable build for this architecture.  <br>
    """
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_INDEX_TIMEOUT_S) as response:  # noqa: S310 - a fixed, configured mirror
            html = response.read().decode("utf-8", errors="replace")
    except OSError as exc:
        raise FleetError(f"Could not read the Kodi mirror at {url}: {exc}") from exc

    names = parse_index(html, arch)
    if not names:
        raise FleetError(f"No stable {arch} Kodi build found at {url}")
    match = _VERSION.search(names[0])
    return names[0], (match.group(1) if match else "unknown")


def fetch_base(context: FleetStepContext) -> StepResult:
    """Download the newest stable Kodi APK and publish it as an artifact.

    **PARAMETERS:**
        `context` (FleetStepContext): Artifact store and resolved config. May supply `arch` and `mirror_url`.  <br>

    **RETURNS:**
        `StepResult`: Carries the published APK under the ``base`` artifact role.  <br>

    **RAISES:**
        `FleetError`: If the mirror cannot be read or the download fails.  <br>
    """
    arch = str(context.config.get("arch", DEFAULT_ARCH))
    url = str(context.config.get("mirror_url", MIRROR_URL))

    context.handle.log(f"Checking the Kodi mirror for the newest stable {arch} build...")
    filename, version = latest_release(arch, url=url)

    published = _published_version(context.artifacts)
    if published == version and not context.config.get("force"):
        context.handle.log(f"Base image is already Kodi {version}; nothing to fetch.")
        return StepResult(summary=f"Base image already at Kodi {version}", facts={"version": version, "downloaded": False})

    context.handle.check_cancelled()
    context.handle.log(f"Downloading Kodi {version}...")
    local = context.workspace / filename
    _download(f"{url}{filename}", local)

    ref = ArtifactRef(kind=BASE, name=filename)
    info = context.artifacts.put(local, ref, meta={"app": APP_ID, "kodi_version": version, "arch": arch})
    context.handle.log(f"Published {ref.wire} ({info.size // (1024 * 1024)}MB)")
    return StepResult(summary=f"Published Kodi {version}", artifacts={"base": ref}, facts={"version": version, "downloaded": True})


def check_update(context: FleetStepContext) -> StepResult:
    """Report whether a newer stable Kodi exists than the published base.

    **RETURNS:**
        `StepResult`: Facts carry `current`, `latest`, and `update_available`.  <br>
    """
    arch = str(context.config.get("arch", DEFAULT_ARCH))
    url = str(context.config.get("mirror_url", MIRROR_URL))
    current = _published_version(context.artifacts)
    _, latest = latest_release(arch, url=url)

    available = bool(latest) and latest != current
    context.handle.log(f"Published: {current or 'none'}; latest stable: {latest}")
    summary = f"Update available: {current or 'none'} -> {latest}" if available else f"Base image is current at {latest}"
    return StepResult(summary=summary, facts={"current": current or None, "latest": latest, "update_available": available})


def install_base(context: DeviceStepContext) -> StepResult:
    """Install the published base APK, unless the device already runs it.

    **RETURNS:**
        `StepResult`: Whether an install happened, and the versions involved.  <br>

    **RAISES:**
        `FleetError`: If no base image has been published.  <br>
    """
    # The published base image is an Android APK. A device on any other
    # platform installs Kodi from its own package source, so this is a skip
    # rather than a failure — the fleet workflow targets every Kodi device.
    platform = context.state.platform
    if platform != ANDROID:
        context.handle.log(f"Base image is an Android APK; {context.device.id} is {platform} and manages Kodi itself.")
        return StepResult(summary=f"{context.device.id}: skipped, not an Android device", facts={"changed": False, "skipped": True, "platform": platform})

    package = IDENTIFIERS[ANDROID]
    installed = context.apps.installed_version(package)
    published = _published_version(context.artifacts)

    if not published:
        raise FleetError("No base image published. Run kodi.fetch_base first.")
    if installed and installed.startswith(published) and not context.config.get("force"):
        context.handle.log(f"Kodi {installed} already installed; skipping the APK push.")
        return StepResult(summary=f"{context.device.id} already on Kodi {installed}", facts={"installed": installed, "changed": False})

    ref = context.artifacts.latest(BASE)
    context.handle.log(f"Installing Kodi {published} (device has {installed or 'none'})...")
    local = context.artifacts.get(ref, context.workspace / ref.name)

    context.handle.check_cancelled()
    context.apps.stop(package)
    context.apps.install(local, identifier=package)

    context.handle.log(f"Kodi {published} installed")
    return StepResult(
        summary=f"Installed Kodi {published} on {context.device.id}",
        facts={"installed": published, "previous": installed or None, "changed": True},
    )


def _published_version(artifacts: Any) -> str:
    """RETURNS: str: The Kodi version of the published base image, or ``""`` if none is published."""
    try:
        found = artifacts.list(BASE)
    except (ArtifactError, OSError) as exc:
        LOGGER.debug("Could not list base images: %s", exc)
        return ""
    if not found:
        return ""
    recorded = found[0].meta.get("kodi_version")
    return str(recorded) if recorded else str(version_key(found[0].ref.name)[0] or "")


def _download(url: str, destination: Path) -> None:
    """Stream a URL to disk in chunks, so a large APK never lands in memory whole.

    **RAISES:**
        `FleetError`: If the download fails.  <br>
    """
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT_S) as response, open(destination, "wb") as handle:  # noqa: S310
            while chunk := response.read(_CHUNK):
                handle.write(chunk)
    except OSError as exc:
        raise FleetError(f"Could not download {url}: {exc}") from exc


def base_meta(artifacts: Any) -> Mapping[str, Any]:
    """RETURNS: Mapping[str, Any]: Metadata for the published base image, or an empty mapping."""
    try:
        found = artifacts.list(BASE)
    except (ArtifactError, OSError):
        return {}
    return dict(found[0].meta) if found else {}


__all__ = [
    "BASE",
    "CHECK_UPDATE",
    "FETCH_BASE",
    "INSTALL_BASE",
    "base_meta",
    "check_update",
    "fetch_base",
    "install_base",
    "is_stable",
    "latest_release",
    "parse_index",
    "version_key",
]
