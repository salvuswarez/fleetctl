"""The `capture_state` / `restore_state` steps every Android vendor pack shares.

A Kodi capture answers "what was this device running". These answer "what was
this device", which is the other half of rebuilding a box that has been wiped:
its `settings`, what was installed on it, what had been switched off, and the
APKs to put the installed things back.

The bodies live here rather than in a vendor pack because none of the work is
vendor-specific — a vendor pack supplies its own quirks and registers these
under its own step id, exactly as it does for `maintain` and `check`.

Effect classes are the important declaration here. Capture is `READ`: it
reads settings, reads the package list, and pulls files. Restore is
`DESTRUCTIVE`: it rewrites system settings and reinstalls packages over
whatever is currently there.
"""

from __future__ import annotations

import logging
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from fleetctl.core.artifacts.ref import ArtifactRef
from fleetctl.core.artifacts.store import require_kind
from fleetctl.core.effects import Capability, Effect
from fleetctl.core.errors import FleetError
from fleetctl.core.workflow.step import DeviceStepContext, StepResult, StepSpec
from fleetctl.packs.android.devicestate import AndroidDeviceStateManager, InstalledPackage, PackageInventory, apk_filename

LOGGER = logging.getLogger(__name__)

DEVICE_STATE = "device-state"

SETTINGS_FILE = "settings.yml"
PACKAGES_FILE = "packages.yml"
APK_DIR = "apks"


def capture_spec(pack_id: str) -> StepSpec:
    """RETURNS: StepSpec: The capture step, registered under `pack_id`."""
    return StepSpec(
        id=f"{pack_id}.capture_state",
        summary="Capture a device's Android settings, package list and APKs so it can be rebuilt.",
        effect=Effect.READ,
        requires=frozenset({Capability.EXEC, Capability.FACTS, Capability.FILES, Capability.SETTINGS}),
        scope="device",
    )


def restore_spec(pack_id: str) -> StepSpec:
    """RETURNS: StepSpec: The restore step, registered under `pack_id`."""
    return StepSpec(
        id=f"{pack_id}.restore_state",
        summary="Rewrite a device's Android settings and reinstall its packages from a snapshot.",
        effect=Effect.DESTRUCTIVE,
        requires=frozenset({Capability.EXEC, Capability.FILES, Capability.SETTINGS, Capability.APPS}),
        scope="device",
    )


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def capture_state(manager: AndroidDeviceStateManager, context: DeviceStepContext) -> StepResult:
    """Capture a device's own configuration and publish it as an artifact.

    **PARAMETERS:**
        `manager` (AndroidDeviceStateManager): Built by the pack from its own quirks and policy.  <br>
        `context` (DeviceStepContext): The device, artifact store, and config. `include_apks` (default true) decides whether the APKs travel with the manifest.  <br>

    **RETURNS:**
        `StepResult`: Carries the published snapshot under the ``device_state`` artifact role.  <br>
    """
    include_apks = bool(context.config.get("include_apks", True))

    context.handle.log(f"Reading settings from {context.device.id}...")
    settings, withheld = manager.read_settings()
    counted = sum(len(entries) for entries in settings.values())
    context.handle.log(f"  {counted} settings across {len(settings)} namespace(s)")
    if withheld:
        # Named, not just counted. A snapshot that quietly omits things is
        # indistinguishable from one the device never had.
        context.handle.log(f"  withheld {len(withheld)} device identifier(s): {', '.join(withheld)}")

    context.handle.check_cancelled()
    context.handle.log("Reading the package list...")
    packages = manager.read_packages(with_paths=include_apks)
    splits = [package.name for package in packages.third_party if package.is_split]
    context.handle.log(f"  {len(packages.third_party)} third-party, {len(packages.system)} system, {len(packages.disabled)} disabled")
    if splits:
        context.handle.log(f"  {len(splits)} split package(s), which only `pm install-multiple` can restore: {', '.join(splits)}")

    staged = context.workspace / "state"
    staged.mkdir(parents=True, exist_ok=True)
    (staged / SETTINGS_FILE).write_text(
        yaml.safe_dump({"settings": settings, "withheld": withheld}, sort_keys=True, allow_unicode=True),
        encoding="utf-8",
    )
    (staged / PACKAGES_FILE).write_text(yaml.safe_dump(_packages_wire(packages), sort_keys=False, allow_unicode=True), encoding="utf-8")

    pulled = 0
    if include_apks:
        pulled = _pull_apks(manager, context, packages, staged / APK_DIR)
    else:
        context.handle.log("Skipping APKs (include_apks=false): this snapshot records what was installed, not how to reinstall it")

    context.handle.check_cancelled()
    name = f"{context.device.id}_{_timestamp()}.tar.gz"
    archive = context.workspace / name
    _pack(staged, archive)

    ref = ArtifactRef(kind=DEVICE_STATE, name=name)
    meta = {
        "device_id": context.device.id,
        "type": context.device.type,
        "model": context.device.model,
        "os_version": context.device.os_version,
        "settings": str(counted),
        "packages": str(len(packages.third_party)),
        "apks": str(pulled),
    }
    info = context.artifacts.put(archive, ref, meta=meta)
    context.handle.log(f"Captured {info.size // (1024 * 1024)}MB to {ref.wire}")
    return StepResult(
        summary=f"Captured {ref.wire}: {counted} settings, {len(packages.third_party)} package(s), {pulled} APK(s)",
        artifacts={"device_state": ref},
        facts={"settings": counted, "packages": len(packages.third_party), "apks": pulled, "withheld": len(withheld)},
    )


def restore_state(manager: AndroidDeviceStateManager, context: DeviceStepContext) -> StepResult:
    """Rewrite a device's settings and reinstall its packages from a snapshot.

    Each of the three halves can be turned off independently (`settings`,
    `packages`, `disabled`), because they fail for unrelated reasons and a
    rebuild is rarely done in one pass: an install needs the network up, a
    settings write does not.

    **PARAMETERS:**
        `manager` (AndroidDeviceStateManager): Built by the pack from its own quirks and policy.  <br>
        `context` (DeviceStepContext): The device, artifact store, and config. `state` names the snapshot; the newest is used when it does not.  <br>

    **RETURNS:**
        `StepResult`: What was applied, skipped and refused.  <br>

    **RAISES:**
        `FleetError`: If the named artifact is not a snapshot, or none exists.  <br>
    """
    named = context.config.get("state")
    ref = require_kind(ArtifactRef.parse(str(named)), DEVICE_STATE) if named else context.artifacts.latest(DEVICE_STATE)
    _warn_on_foreign_snapshot(context, ref)

    context.handle.log(f"Restoring {ref.wire} to {context.device.id}...")
    local = context.artifacts.get(ref, context.workspace / ref.name)
    unpacked = context.workspace / "state"
    with tarfile.open(local, "r:gz") as archive:
        archive.extractall(unpacked, filter="data")

    applied: list[str] = []
    skipped: list[str] = []
    if bool(context.config.get("settings", True)):
        context.handle.check_cancelled()
        stored = _read_yaml(unpacked / SETTINGS_FILE).get("settings", {})
        applied, skipped = manager.apply_settings(stored if isinstance(stored, dict) else {})
        context.handle.log(f"Applied {len(applied)} setting(s), skipped {len(skipped)} the policy will not replay")

    manifest = _read_yaml(unpacked / PACKAGES_FILE)
    installed: list[str] = []
    refused: list[str] = []
    if bool(context.config.get("packages", True)):
        installed, refused = _install_all(manager, context, manifest, unpacked / APK_DIR)

    disabled: list[str] = []
    if bool(context.config.get("disabled", True)):
        context.handle.check_cancelled()
        wanted = [str(name) for name in manifest.get("disabled", []) if name]
        disabled = manager.apply_disabled(wanted)
        if wanted:
            context.handle.log(f"Disabled {len(disabled)}/{len(wanted)} package(s)")

    return StepResult(
        summary=f"Restored {ref.wire} to {context.device.id}: {len(applied)} setting(s), {len(installed)} package(s), {len(disabled)} disabled",
        facts={
            "state": ref.wire,
            "settings_applied": len(applied),
            "settings_skipped": len(skipped),
            "installed": len(installed),
            "refused": refused,
            "disabled": len(disabled),
        },
    )


def _pull_apks(manager: AndroidDeviceStateManager, context: DeviceStepContext, packages: PackageInventory, destination: Path) -> int:
    """Pull every third-party package's APKs, tolerating one that will not come.

    A single unreadable package must not cost the whole snapshot: the settings
    and the manifest are the part that cannot be reconstructed from anywhere
    else, and an APK usually can be.

    **RETURNS:**
        `int`: How many APK files landed.  <br>
    """
    pulled = 0
    for package in packages.third_party:
        context.handle.check_cancelled()
        if not package.apks:
            context.handle.log(f"  {package.name}: no APK path reported, recorded by name only")
            continue
        try:
            written = manager.pull_apks(package, destination)
        except FleetError as exc:
            context.handle.log(f"  {package.name}: could not pull ({exc}); recorded by name only")
            continue
        pulled += len(written)
        detail = f" ({len(written)} splits)" if len(written) > 1 else ""
        context.handle.log(f"  {package.name}{detail}")
    return pulled


def _install_all(
    manager: AndroidDeviceStateManager,
    context: DeviceStepContext,
    manifest: dict[str, Any],
    apk_dir: Path,
) -> tuple[list[str], list[str]]:
    """Reinstall what the snapshot carried APKs for.

    **RETURNS:**
        `tuple[list[str], list[str]]`: Packages installed, and packages the snapshot named but could not put back.  <br>
    """
    installed: list[str] = []
    refused: list[str] = []
    for entry in manifest.get("third_party", []):
        context.handle.check_cancelled()
        name = str(entry.get("name", ""))
        if not name:
            continue
        if not manager.policy.is_installable(name):
            context.handle.log(f"  {name}: refused by policy (a system package cannot be reinstalled over itself)")
            refused.append(name)
            continue

        files = [apk_dir / str(leaf) for leaf in entry.get("files", [])]
        present = [path for path in files if path.is_file()]
        if not present:
            context.handle.log(f"  {name}: no APK in this snapshot, skipped")
            refused.append(name)
            continue

        try:
            manager.install(name, present)
        except FleetError as exc:
            # One app that will not install is not a reason to abandon the
            # rest of a rebuild.
            context.handle.log(f"  {name}: install failed ({exc})")
            refused.append(name)
            continue
        installed.append(name)
        context.handle.log(f"  {name}: installed")
    return installed, refused


def _warn_on_foreign_snapshot(context: DeviceStepContext, ref: ArtifactRef) -> None:
    """Say so when a snapshot came from different hardware.

    Not refused. Rebuilding a replacement box from the dead one's snapshot is
    a legitimate and likely use — but settings written across a model boundary
    are the most likely explanation for a restore that lands and misbehaves,
    so it belongs in the log either way.
    """
    info = next((item for item in context.artifacts.list(DEVICE_STATE) if item.ref.name == ref.name), None)
    if info is None:
        return
    source = str(info.meta.get("device_id", ""))
    source_model = str(info.meta.get("model", ""))
    if source and source != context.device.id:
        context.handle.log(f"Note: this snapshot was taken from {source} ({source_model or 'unknown model'}), not {context.device.id}")


def _packages_wire(packages: PackageInventory) -> dict[str, Any]:
    """RETURNS: dict[str, Any]: The package inventory as it is stored, with local APK filenames rather than device paths."""
    return {
        "third_party": [
            {
                "name": package.name,
                "version": package.version,
                "split": package.is_split,
                "files": [_local_name(package, index) for index in range(len(package.apks))],
            }
            for package in packages.third_party
        ],
        "disabled": list(packages.disabled),
        "system": list(packages.system),
    }


def _local_name(package: InstalledPackage, index: int) -> str:
    """RETURNS: str: The filename `pull_apks` writes for one of a package's APKs."""
    return apk_filename(package.name, package.apks[index], index)


def _pack(source: Path, destination: Path) -> None:
    """Write the staged snapshot to a gzipped tar.

    Written as GNU rather than PAX for the same reason a Kodi build is: a
    set-top device's `tar` cannot read PAX long names, and a snapshot should
    stay openable on the hardware it describes.
    """
    with tarfile.open(destination, "w:gz", format=tarfile.GNU_FORMAT) as archive:
        for entry in sorted(source.iterdir()):
            archive.add(entry, arcname=entry.name)


def _read_yaml(path: Path) -> dict[str, Any]:
    """RETURNS: dict[str, Any]: A parsed member of an unpacked snapshot, or empty when it is absent."""
    if not path.is_file():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}
