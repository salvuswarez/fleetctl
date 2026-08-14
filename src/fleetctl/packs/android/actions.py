"""Android device actions, as functions over a `CommandRunner`."""

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass
from typing import Iterable, Mapping

from fleetctl.core.effects import Effect
from fleetctl.core.transport.base import CommandRunner
from fleetctl.packs.android.quirks import AndroidQuirks

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PackageOutcome:
    """What happened when a package was disabled.

    **PARAMETERS:**
        `package` (str): The package acted on.  <br>
        `disabled` (bool): Whether it is actually disabled now.  <br>
        `verified` (bool): Whether that was confirmed by re-reading device state rather than assumed from the command returning.  <br>
    """

    package: str
    disabled: bool
    verified: bool


def read_facts(runner: CommandRunner) -> dict[str, str]:
    """Collect identifying properties from a device.

    **PARAMETERS:**
        `runner` (CommandRunner): Connection to the device.  <br>

    **RETURNS:**
        `dict[str, str]`: Any of `model`, `manufacturer`, `serial`, `os_version`, `name`, `abi`, `abilist` that could be read. A missing key means the device did not answer, which is different from answering with an empty value.  <br>
    """
    probes = {
        "model": "getprop ro.product.model",
        "manufacturer": "getprop ro.product.manufacturer",
        "serial": "getprop ro.serialno",
        "os_version": "getprop ro.build.version.release",
        "name": "settings get global device_name",
        # Which machine code this device can execute. A Kodi profile carries
        # compiled binary addons, so a build shaped on one device is only
        # deployable to another that can run them -- a 64-bit-only Android TV
        # cannot execute the 32-bit ARM binaries a Fire Stick capture carries.
        # `abilist` is the authority (a 64-bit device usually still runs
        # 32-bit); `abi` is only its preferred one.
        "abi": "getprop ro.product.cpu.abi",
        "abilist": "getprop ro.product.cpu.abilist",
    }
    facts: dict[str, str] = {}
    for key, command in probes.items():
        value = runner.exec_ok(command, effect=Effect.READ).strip()
        # `settings get` prints the literal string "null" for an unset value.
        if value and value.lower() != "null":
            facts[key] = value
    return facts


def list_disabled_packages(runner: CommandRunner) -> set[str]:
    """RETURNS: set[str]: Packages the device currently reports as disabled."""
    output = runner.exec_ok("pm list packages -d", effect=Effect.READ)
    return {line.partition(":")[2].strip() for line in output.splitlines() if line.strip().startswith("package:")}


def disable_packages(runner: CommandRunner, packages: Iterable[str], quirks: AndroidQuirks) -> list[PackageOutcome]:
    """Disable packages, reporting per-package whether it actually took.

    **PARAMETERS:**
        `runner` (CommandRunner): Connection to the device.  <br>
        `packages` (Iterable[str]): Packages to disable.  <br>
        `quirks` (AndroidQuirks): Whether verification is required here.  <br>

    **RETURNS:**
        `list[PackageOutcome]`: One entry per requested package, in order.  <br>
    """
    requested = list(packages)
    for package in requested:
        runner.exec_ok(f"pm disable-user --user 0 {shlex.quote(package)}", effect=Effect.DESTRUCTIVE)

    if not quirks.verify_disable_user:
        return [PackageOutcome(package=package, disabled=True, verified=False) for package in requested]

    disabled = list_disabled_packages(runner)
    return [PackageOutcome(package=package, disabled=package in disabled, verified=True) for package in requested]


def apply_settings(runner: CommandRunner, settings: Mapping[str, Mapping[str, str]]) -> list[str]:
    """Apply namespaced settings, e.g. ``{"global": {"window_animation_scale": "0.0"}}``.

    **PARAMETERS:**
        `runner` (CommandRunner): Connection to the device.  <br>
        `settings` (Mapping[str, Mapping[str, str]]): Namespace to key/value pairs.  <br>

    **RETURNS:**
        `list[str]`: Human-readable descriptions of what was set.  <br>
    """
    changes: list[str] = []
    for namespace, entries in settings.items():
        for key, value in entries.items():
            runner.exec_ok(f"settings put {shlex.quote(namespace)} {shlex.quote(key)} {shlex.quote(str(value))}", effect=Effect.MUTATING)
            changes.append(f"{namespace}.{key} = {value}")
    return changes


def remove_paths(runner: CommandRunner, paths: Iterable[str]) -> list[str]:
    """Delete paths on the device.

    **PARAMETERS:**
        `runner` (CommandRunner): Connection to the device.  <br>
        `paths` (Iterable[str]): Absolute paths to remove.  <br>

    **RETURNS:**
        `list[str]`: The paths that were acted on.  <br>
    """
    removed: list[str] = []
    for path in paths:
        runner.exec_ok(f"rm -rf {shlex.quote(path)}", effect=Effect.DESTRUCTIVE)
        removed.append(path)
    return removed


def trim_caches(runner: CommandRunner, reserve: str = "16G") -> None:
    """Ask the platform to free cached data down to `reserve` free space."""
    runner.exec_ok(f"pm trim-caches {shlex.quote(reserve)}", effect=Effect.DESTRUCTIVE)


def install_package(runner: CommandRunner, remote_apk: str) -> None:
    """Install an APK already staged on the device.

    **RAISES:**
        `CommandFailedError`: If the install failed.  <br>
    """
    runner.exec(f"pm install -r {shlex.quote(remote_apk)}", effect=Effect.DESTRUCTIVE)


def installed_version(runner: CommandRunner, package: str) -> str:
    """RETURNS: str: The installed `versionName` for `package`, or ``""`` if absent."""
    output = runner.exec_ok(f"dumpsys package {shlex.quote(package)}", effect=Effect.READ)
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("versionName="):
            return stripped.partition("=")[2].strip()
    return ""


def installed_abi(runner: CommandRunner, package: str) -> str:
    """RETURNS: str: The `primaryCpuAbi` an installed package runs as, or ``""`` if absent or not reported.

    A package with no native code reports ``null`` here, which is not an
    architecture and must not be returned as one.
    """
    output = runner.exec_ok(f"dumpsys package {shlex.quote(package)}", effect=Effect.READ)
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("primaryCpuAbi="):
            value = stripped.partition("=")[2].strip()
            return "" if value.lower() in ("", "null") else value
    return ""


def power_state(runner: CommandRunner) -> str:
    """Read whether the device is awake, without waking it.

    A set-top device stays on the network while asleep — it answers ping, TCP
    and ADB throughout — so reachability says nothing about whether anyone is
    watching it. This is the signal that does.

    `grep -m1` is deliberately not used: it closes the pipe on a still-writing
    `dumpsys`, which prints "Failed to write while dumping service power" to
    the merged stream and makes a clean read look like a failure.

    **PARAMETERS:**
        `runner` (CommandRunner): Connection to the device.  <br>

    **RETURNS:**
        `str`: The lowercased wakefulness, one of ``awake``, ``asleep``, ``dozing``, ``dreaming``, or ``""`` when the device did not answer.  <br>
    """
    output = runner.exec_ok("dumpsys power | grep mWakefulness=", effect=Effect.READ)
    for line in output.splitlines():
        _, separator, value = line.strip().partition("mWakefulness=")
        if separator and value.strip():
            return value.strip().split()[0].lower()
    return ""


def launch_activity(runner: CommandRunner, package: str) -> str:
    """Resolve a package's launchable activity, without knowing what the package is.

    Asks the platform rather than hardcoding a component: an app pack must not
    have to name its own activity here, and the answer differs between a TV
    launcher entry and a phone one. Leanback is tried first because on a TV
    that is the entry the launcher itself would use.

    **PARAMETERS:**
        `runner` (CommandRunner): Connection to the device.  <br>
        `package` (str): Package to resolve.  <br>

    **RETURNS:**
        `str`: A ``package/activity`` component, or ``""`` when the package exposes no launchable activity.  <br>
    """
    for category in ("android.intent.category.LEANBACK_LAUNCHER", "android.intent.category.LAUNCHER"):
        output = runner.exec_ok(
            f"cmd package resolve-activity --brief -c {category} -a android.intent.action.MAIN {shlex.quote(package)}",
            effect=Effect.READ,
        )
        # The component is the last line; the preceding lines are match detail.
        for line in reversed(output.splitlines()):
            candidate = line.strip()
            if candidate.startswith(f"{package}/"):
                return candidate
    return ""


def is_running(runner: CommandRunner, package: str) -> bool:
    """RETURNS: bool: Whether the package currently has a process."""
    return bool(runner.exec_ok(f"pidof {shlex.quote(package)}", effect=Effect.READ).strip())


def start_app(runner: CommandRunner, component: str) -> None:
    """Start an activity by its `package/activity` component."""
    runner.exec_ok(f"am start -n {shlex.quote(component)}", effect=Effect.MUTATING)


def stop_app(runner: CommandRunner, package: str) -> None:
    """Force-stop an app so its files can be replaced safely."""
    runner.exec_ok(f"am force-stop {shlex.quote(package)}", effect=Effect.MUTATING)


def reboot(runner: CommandRunner) -> None:
    """Reboot the device."""
    runner.exec_ok("reboot", effect=Effect.DESTRUCTIVE)


def health(runner: CommandRunner, *, storage_path: str = "/sdcard") -> dict[str, str]:
    """Collect a quick health picture from a device.

    **PARAMETERS:**
        `runner` (CommandRunner): Connection to the device.  <br>
        `storage_path` (str): Filesystem to report free space for.  <br>

    **RETURNS:**
        `dict[str, str]`: Facts plus `uptime` and `free_mb` where the device answered.  <br>
    """
    facts = read_facts(runner)
    uptime = runner.exec_ok("cat /proc/uptime", effect=Effect.READ).split(" ")[0]
    if uptime:
        facts["uptime_hours"] = f"{float(uptime) / 3600:.1f}" if uptime.replace(".", "", 1).isdigit() else uptime
    free = runner.exec_ok(f"df -k {shlex.quote(storage_path)}", effect=Effect.READ).splitlines()
    if len(free) >= 2:
        for value in reversed(free[-1].split()):
            if value.isdigit():
                facts["free_mb"] = str(int(value) // 1024)
                break
    return facts
