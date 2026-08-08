"""POSIX host actions, as functions over a `CommandRunner`."""

from __future__ import annotations

import logging
import posixpath
import shlex
from typing import Iterable

from ...core.effects import Effect
from ...core.errors import FleetError
from ...core.transport.base import CommandRunner

LOGGER = logging.getLogger(__name__)

# Read from /etc/os-release, which every systemd distribution ships. Parsed
# rather than shelled out to per key so a probe costs one round trip.
_OS_RELEASE = "cat /etc/os-release"


def read_facts(runner: CommandRunner) -> dict[str, str]:
    """Collect identifying properties from a POSIX host.

    **PARAMETERS:**
        `runner` (CommandRunner): Connection to the host.  <br>

    **RETURNS:**
        `dict[str, str]`: Any of `model`, `manufacturer`, `os_version`, `name`, `kernel`, `arch` that could be read. A missing key means the host did not answer, which is different from answering with an empty value.  <br>
    """
    facts: dict[str, str] = {}

    release = parse_os_release(runner.exec_ok(_OS_RELEASE, effect=Effect.READ))
    # `ID` is the stable machine-readable distribution name (`arch`, `debian`,
    # `steamos`); `NAME` is the human one. A pack claims on the former.
    if release.get("ID"):
        facts["model"] = release["ID"]
    if release.get("NAME"):
        facts["manufacturer"] = release["NAME"]
    if release.get("VERSION_ID"):
        facts["os_version"] = release["VERSION_ID"]

    # `uname -n` rather than `hostname`: the latter is a separate package
    # (inetutils) that SteamOS 3.8 does not ship, so it exits 127 and the
    # host's name was silently dropped from the facts. `uname` is POSIX and
    # already needed for the two reads below.
    for key, command in (("name", "uname -n"), ("kernel", "uname -r"), ("arch", "uname -m")):
        value = runner.exec_ok(command, effect=Effect.READ).strip()
        if value:
            facts[key] = value
    return facts


def parse_os_release(text: str) -> dict[str, str]:
    """Parse ``/etc/os-release`` into a mapping.

    **PARAMETERS:**
        `text` (str): Raw file contents.  <br>

    **RETURNS:**
        `dict[str, str]`: Declared keys with surrounding quotes stripped. Comments, blanks, and malformed lines are skipped rather than raising — a probe sweeps hosts that may answer with anything.  <br>
    """
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        parsed[key.strip()] = value.strip().strip('"').strip("'")
    return parsed


def expand_home(runner: CommandRunner, path: str) -> str:
    """Resolve a leading ``~`` against the host's home directory.

    Every command here quotes its arguments, which stops the remote shell
    expanding `~` — an unexpanded path silently targets a literal `~`
    directory that does not exist, so the command succeeds and does nothing.

    **PARAMETERS:**
        `runner` (CommandRunner): Connection to the host.  <br>
        `path` (str): A path that may start with ``~``.  <br>

    **RETURNS:**
        `str`: The path with `~` replaced, or unchanged when it has none.  <br>

    **RAISES:**
        `FleetError`: If the home directory could not be read, rather than acting on a path that is still wrong.  <br>
    """
    if not path.startswith("~"):
        return path
    home = runner.exec_ok("echo $HOME", effect=Effect.READ).strip()
    if not home:
        raise FleetError("Could not resolve the home directory to expand a '~' path")
    return posixpath.join(home, path[1:].lstrip("/"))


def remove_paths(runner: CommandRunner, paths: Iterable[str]) -> list[str]:
    """Delete paths on the host.

    **PARAMETERS:**
        `runner` (CommandRunner): Connection to the host.  <br>
        `paths` (Iterable[str]): Absolute paths to remove.  <br>

    **RETURNS:**
        `list[str]`: The paths that were acted on.  <br>
    """
    removed: list[str] = []
    for path in paths:
        runner.exec_ok(f"rm -rf {shlex.quote(expand_home(runner, path))}", effect=Effect.DESTRUCTIVE)
        removed.append(path)
    return removed


def reboot(runner: CommandRunner) -> None:
    """Reboot the host."""
    runner.exec_ok("systemctl reboot", effect=Effect.DESTRUCTIVE)


def trim_journal(runner: CommandRunner, retention: str) -> str:
    """Drop journal entries older than `retention`.

    **PARAMETERS:**
        `runner` (CommandRunner): Connection to the host.  <br>
        `retention` (str): A systemd time span, e.g. ``7d``.  <br>

    **RETURNS:**
        `str`: What journalctl reported, or ``""`` if it could not run.  <br>
    """
    return runner.exec_ok(f"journalctl --user --vacuum-time={shlex.quote(retention)}", effect=Effect.DESTRUCTIVE)


def remove_unused_flatpaks(runner: CommandRunner) -> str:
    """Remove Flatpak runtimes no installed application still needs.

    **RETURNS:**
        `str`: What flatpak reported, or ``""`` if it could not run.  <br>
    """
    return runner.exec_ok("flatpak uninstall --unused --assumeyes", effect=Effect.DESTRUCTIVE)


def disk_usage(runner: CommandRunner, path: str) -> str:
    """RETURNS: str: Human-readable size of `path`, or ``""`` when it could not be measured."""
    output = runner.exec_ok(f"du -sh {shlex.quote(path)}", effect=Effect.READ)
    return output.split("\t")[0].strip() if output else ""


def health(runner: CommandRunner, *, storage_path: str = "/") -> dict[str, str]:
    """Collect a quick health picture from a host.

    **PARAMETERS:**
        `runner` (CommandRunner): Connection to the host.  <br>
        `storage_path` (str): Filesystem to report free space for.  <br>

    **RETURNS:**
        `dict[str, str]`: Facts plus `uptime_hours` and `free_mb` where the host answered.  <br>
    """
    facts = read_facts(runner)

    uptime = runner.exec_ok("cat /proc/uptime", effect=Effect.READ).split(" ")[0]
    if uptime:
        facts["uptime_hours"] = f"{float(uptime) / 3600:.1f}" if uptime.replace(".", "", 1).isdigit() else uptime

    free = runner.exec_ok(f"df -k {shlex.quote(storage_path)}", effect=Effect.READ).splitlines()
    if len(free) >= 2:
        columns = free[-1].split()
        # df's available column is the fourth on GNU coreutils, but a long
        # device name wraps the row; index from the right, where the layout
        # is stable: ... <used> <available> <use%> <mount>.
        if len(columns) >= 3 and columns[-3].isdigit():
            facts["free_mb"] = str(int(columns[-3]) // 1024)
    return facts
