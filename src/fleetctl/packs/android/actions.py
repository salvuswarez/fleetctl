"""Android device actions, as functions over a `CommandRunner`.

Functions rather than a class: these have no state and no lifecycle beyond
the runner they are handed, and a class with one method per verb and no
state is a function wearing a costume. It also keeps the dependency narrow —
none of this needs file transfer or reachability.

Vendor differences arrive as `AndroidQuirks`, never as a branch on a model
string.
"""

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass
from typing import Iterable, Mapping

from ...core.effects import Effect
from ...core.transport.base import CommandRunner
from .quirks import AndroidQuirks

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
        `dict[str, str]`: Any of `model`, `manufacturer`, `serial`, `os_version`, `name` that could be read. A missing key means the device did not answer, which is different from answering with an empty value.  <br>
    """
    probes = {
        "model": "getprop ro.product.model",
        "manufacturer": "getprop ro.product.manufacturer",
        "serial": "getprop ro.serialno",
        "os_version": "getprop ro.build.version.release",
        "name": "settings get global device_name",
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

    `pm disable-user` can fail silently for system packages from a non-root
    shell on some vendor builds, so where the quirk is declared this re-reads
    the device's own list rather than trusting the command's return. The
    predecessor reported success for ~90 packages having verified none.

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


def stop_app(runner: CommandRunner, package: str) -> None:
    """Force-stop an app so its files can be replaced safely."""
    runner.exec_ok(f"am force-stop {shlex.quote(package)}", effect=Effect.MUTATING)


def reboot(runner: CommandRunner) -> None:
    """Reboot the device."""
    runner.exec_ok("reboot", effect=Effect.DESTRUCTIVE)
