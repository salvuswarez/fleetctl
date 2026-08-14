"""Snapshotting what an Android device *is*, so a wiped one can be rebuilt.

Distinct from `state.py`, which snapshots what an *application* keeps on a
device. This is the device's own configuration: its `settings` namespaces, the
packages installed and disabled on it, and the APKs those packages were
installed from.

Shared by every Android vendor pack because none of it is vendor knowledge —
`settings` and `pm` are the platform's. A vendor pack registers the steps
under its own id and supplies its own quirks; nothing here knows which vendor
it is talking to.

Two things a live device settled that the documentation would not:

- **Most third-party packages ship as split APKs.** 5 of 9 on the surveyed
  device carried between 2 and 5 splits. `pm list packages -f` reports only
  the base, and installing that alone yields an app missing its density,
  language and ABI resources — so the paths come from `pm path` per package
  and go back through `pm install-multiple`.
- **The install directory is readable but not listable.** Every APK pulled
  cleanly by absolute path; none would have been found by listing.
"""

from __future__ import annotations

import fnmatch
import logging
import posixpath
import re
import shlex
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from fleetctl.core.effects import Effect
from fleetctl.core.errors import TransportError
from fleetctl.core.transport.base import Transport
from fleetctl.packs.android import actions
from fleetctl.packs.android.quirks import AndroidQuirks

LOGGER = logging.getLogger(__name__)

# `settings list` prints `key=value`, and a value may itself contain newlines
# — an enabled-accessibility-services list does. A line is therefore only a
# new key when it looks like one; anything else continues the previous value.
_SETTING_LINE = re.compile(r"^([A-Za-z0-9_.:-]+)=(.*)$", re.DOTALL)

_DATA_PACKAGE = "fleetctl.packs.android.data"


def _load(name: str) -> dict[str, Any]:
    """RETURNS: dict[str, Any]: A parsed data file shipped with the shared Android base."""
    text = resources.files(_DATA_PACKAGE).joinpath(name).read_text(encoding="utf-8")
    loaded = yaml.safe_load(text)
    return loaded if isinstance(loaded, dict) else {}


@dataclass(frozen=True, slots=True)
class DeviceStatePolicy:
    """Which settings a snapshot may carry, and which it may write back.

    Two lists rather than one because the questions differ: `never_capture`
    is about what may leave the device at all, `never_restore` about what is
    safe to assert on a *different* device. A boot counter is harmless to
    record and wrong to replay.

    **PARAMETERS:**
        `capture_namespaces` (tuple[str, ...]): `settings` namespaces to read.  <br>
        `never_capture` (tuple[str, ...]): fnmatch patterns against ``<namespace>.<key>``; matches are dropped before the artifact is written.  <br>
        `never_restore` (tuple[str, ...]): fnmatch patterns; matches are kept in the artifact and skipped on restore.  <br>
        `never_install` (tuple[str, ...]): fnmatch patterns against package names never reinstalled from a snapshot.  <br>
    """

    capture_namespaces: tuple[str, ...] = ("global", "system", "secure")
    never_capture: tuple[str, ...] = ()
    never_restore: tuple[str, ...] = ()
    never_install: tuple[str, ...] = ()

    @classmethod
    def shipped(cls) -> DeviceStatePolicy:
        """RETURNS: DeviceStatePolicy: The policy in `data/device_state.yml`."""
        return cls.from_mapping(_load("device_state.yml"))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> DeviceStatePolicy:
        """RETURNS: DeviceStatePolicy: The declared policy, with defaults for anything unset."""

        def _tuple(key: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
            value = data.get(key)
            return tuple(str(item) for item in value) if isinstance(value, list) else default

        return cls(
            capture_namespaces=_tuple("capture_namespaces", ("global", "system", "secure")),
            never_capture=_tuple("never_capture"),
            never_restore=_tuple("never_restore"),
            never_install=_tuple("never_install"),
        )

    def is_capturable(self, namespace: str, key: str) -> bool:
        """RETURNS: bool: Whether this setting may be written to an artifact."""
        return not _matches(f"{namespace}.{key}", self.never_capture)

    def is_restorable(self, namespace: str, key: str) -> bool:
        """RETURNS: bool: Whether this setting may be written back to a device."""
        return not _matches(f"{namespace}.{key}", self.never_restore)

    def is_installable(self, package: str) -> bool:
        """RETURNS: bool: Whether this package may be reinstalled from a snapshot."""
        return not _matches(package, self.never_install)


@dataclass(frozen=True, slots=True)
class InstalledPackage:
    """One installed package and the APKs it was installed from.

    **PARAMETERS:**
        `name` (str): Package identifier.  <br>
        `apks` (tuple[str, ...]): On-device APK paths, base first — more than one when the package is split.  <br>
        `version` (str): Installed `versionName`, or empty when the device did not say.  <br>
    """

    name: str
    apks: tuple[str, ...] = ()
    version: str = ""

    @property
    def is_split(self) -> bool:
        """RETURNS: bool: Whether this package needs `pm install-multiple` rather than `pm install`."""
        return len(self.apks) > 1


@dataclass(frozen=True, slots=True)
class PackageInventory:
    """What is installed on a device and what has been switched off.

    **PARAMETERS:**
        `third_party` (tuple[InstalledPackage, ...]): Packages not shipped in the system image — the ones a rebuild has to put back.  <br>
        `system` (tuple[str, ...]): System package names, recorded for reference; their APKs cannot be reinstalled.  <br>
        `disabled` (tuple[str, ...]): Packages currently disabled, so a restore can reproduce the debloat.  <br>
    """

    third_party: tuple[InstalledPackage, ...] = ()
    system: tuple[str, ...] = ()
    disabled: tuple[str, ...] = ()


def _matches(candidate: str, patterns: Iterable[str]) -> bool:
    """RETURNS: bool: Whether `candidate` matches any fnmatch pattern, case-insensitively."""
    folded = candidate.lower()
    return any(fnmatch.fnmatch(folded, pattern.lower()) for pattern in patterns)


def parse_settings(output: str) -> dict[str, str]:
    """Parse one `settings list <namespace>` dump.

    **PARAMETERS:**
        `output` (str): Raw command output.  <br>

    **RETURNS:**
        `dict[str, str]`: Key to value. A value spanning several lines is
        rejoined onto its key rather than silently truncated at the newline.  <br>
    """
    parsed: dict[str, str] = {}
    current = ""
    for line in output.splitlines():
        match = _SETTING_LINE.match(line)
        if match:
            current = match.group(1)
            parsed[current] = match.group(2)
        elif current:
            parsed[current] = f"{parsed[current]}\n{line}"
    return parsed


class AndroidDeviceStateManager:
    """Reads and rewrites a device's own configuration.

    **PARAMETERS:**
        `transport` (Transport): Connection to the device.  <br>
        `quirks` (AndroidQuirks): Vendor deviations, notably where an APK may be staged for install.  <br>
        `policy` (DeviceStatePolicy | None): What may be captured and replayed. Defaults to the shipped policy.  <br>
    """

    def __init__(self, transport: Transport, quirks: AndroidQuirks | None = None, policy: DeviceStatePolicy | None = None) -> None:
        self._transport = transport
        self._quirks = quirks or AndroidQuirks()
        self._policy = policy or DeviceStatePolicy.shipped()

    @property
    def policy(self) -> DeviceStatePolicy:
        """RETURNS: DeviceStatePolicy: The policy this manager applies."""
        return self._policy

    # -- Reading -----------------------------------------------------------

    def read_settings(self) -> tuple[dict[str, dict[str, str]], list[str]]:
        """Read every configured `settings` namespace.

        **RETURNS:**
            `tuple[dict[str, dict[str, str]], list[str]]`: The capturable
            settings by namespace, and the ``<namespace>.<key>`` names withheld
            by `never_capture` — reported rather than dropped silently, because
            a snapshot that quietly omits things is not a snapshot.  <br>
        """
        captured: dict[str, dict[str, str]] = {}
        withheld: list[str] = []
        for namespace in self._policy.capture_namespaces:
            output = self._transport.exec_ok(f"settings list {shlex.quote(namespace)}", effect=Effect.READ)
            entries: dict[str, str] = {}
            for key, value in parse_settings(output).items():
                if self._policy.is_capturable(namespace, key):
                    entries[key] = value
                else:
                    withheld.append(f"{namespace}.{key}")
            captured[namespace] = entries
        return captured, sorted(withheld)

    def read_packages(self, *, with_paths: bool = True) -> PackageInventory:
        """Read what is installed, what is disabled, and where the APKs are.

        `pm path` is called per third-party package rather than reading
        `pm list packages -f` once, because that reports only the base APK.
        Most third-party packages on a modern device are split, and installing
        a base without its splits produces an app missing resources it needs.

        **PARAMETERS:**
            `with_paths` (bool): Whether to resolve APK paths. Defaults to ``True``; ``False`` records names only, which is much faster.  <br>

        **RETURNS:**
            `PackageInventory`: What the device reported.  <br>
        """
        third_party_names = _package_names(self._transport.exec_ok("pm list packages -3", effect=Effect.READ))
        every_name = _package_names(self._transport.exec_ok("pm list packages", effect=Effect.READ))
        disabled = _package_names(self._transport.exec_ok("pm list packages -d", effect=Effect.READ))

        third_party: list[InstalledPackage] = []
        for name in third_party_names:
            apks = self._apk_paths(name) if with_paths else ()
            third_party.append(InstalledPackage(name=name, apks=apks, version=actions.installed_version(self._transport, name)))

        return PackageInventory(
            third_party=tuple(third_party),
            system=tuple(sorted(set(every_name) - set(third_party_names))),
            disabled=tuple(sorted(disabled)),
        )

    def pull_apks(self, package: InstalledPackage, destination: Path) -> list[Path]:
        """Pull every APK a package was installed from.

        **PARAMETERS:**
            `package` (InstalledPackage): The package, carrying its on-device paths.  <br>
            `destination` (Path): Directory to write into; created if absent.  <br>

        **RETURNS:**
            `list[Path]`: The files written, in the order `pm path` reported them — base first, which is the order `pm install-multiple` wants.  <br>

        **RAISES:**
            `TransportError`: If a pull failed, or produced something that is not an APK.  <br>
        """
        destination.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for index, remote in enumerate(package.apks):
            local = destination / apk_filename(package.name, remote, index)
            self._transport.get(remote, local)
            # An APK is a zip. Checking the local header costs nothing and is
            # the difference between storing a package and storing a zero-byte
            # file that only fails years later, at a restore.
            if local.read_bytes()[:2] != b"PK":
                raise TransportError(f"Pulled {remote} from {package.name} but it is not an APK", target=self._transport.target)
            written.append(local)
        return written

    # -- Writing -----------------------------------------------------------

    def apply_settings(self, settings: Mapping[str, Mapping[str, str]]) -> tuple[list[str], list[str]]:
        """Write captured settings back, skipping anything `never_restore` names.

        **PARAMETERS:**
            `settings` (Mapping[str, Mapping[str, str]]): Namespace to key/value pairs, as captured.  <br>

        **RETURNS:**
            `tuple[list[str], list[str]]`: What was applied and what was skipped, both as ``<namespace>.<key>``.  <br>
        """
        applied: list[str] = []
        skipped: list[str] = []
        for namespace, entries in settings.items():
            writable = {}
            for key, value in entries.items():
                if self._policy.is_restorable(namespace, key):
                    writable[key] = value
                else:
                    skipped.append(f"{namespace}.{key}")
            if writable:
                actions.apply_settings(self._transport, {namespace: writable})
                applied.extend(f"{namespace}.{key}" for key in writable)
        return sorted(applied), sorted(skipped)

    def apply_disabled(self, disabled: Sequence[str]) -> list[str]:
        """Reproduce a captured debloat.

        **PARAMETERS:**
            `disabled` (Sequence[str]): Package names that were disabled when the snapshot was taken.  <br>

        **RETURNS:**
            `list[str]`: Packages that are disabled afterwards — read back from the device where the pack's quirks say the command cannot be trusted.  <br>
        """
        if not disabled:
            return []
        outcomes = actions.disable_packages(self._transport, disabled, self._quirks)
        return [outcome.package for outcome in outcomes if outcome.disabled]

    def install(self, package_name: str, apks: Sequence[Path]) -> None:
        """Reinstall a package from the APKs a snapshot carried.

        A split package goes back through `pm install-multiple`, which is the
        only command that installs a base and its splits as one package. The
        staging directory comes from the pack's quirks and is deliberately not
        external storage: from Android 11 `/sdcard` is a FUSE mount the
        installer has no permission to read, so an install from there fails
        after a transfer that plainly succeeded.

        Takes the name and the local files rather than an `InstalledPackage`,
        whose `apks` are the paths on the device it was captured from — paths
        that mean nothing on the device being restored to.

        **PARAMETERS:**
            `package_name` (str): The package expected to be present afterwards.  <br>
            `apks` (Sequence[Path]): Local APKs, base first.  <br>

        **RAISES:**
            `TransportError`: If nothing was supplied, or the package is absent afterwards.  <br>
        """
        if not apks:
            raise TransportError(f"No APK to install for {package_name}", target=self._transport.target)

        staged: list[str] = []
        try:
            for apk in apks:
                remote = posixpath.join(self._quirks.apk_staging_dir, apk.name)
                self._transport.exec_ok(f"rm -f {shlex.quote(remote)}", effect=Effect.DESTRUCTIVE)
                self._transport.put(apk, remote, effect=Effect.DESTRUCTIVE)
                staged.append(remote)

            quoted = " ".join(shlex.quote(remote) for remote in staged)
            command = f"pm install-multiple -r {quoted}" if len(staged) > 1 else f"pm install -r {quoted}"
            self._transport.exec(command, effect=Effect.DESTRUCTIVE, timeout_s=_install_timeout(apks))
        finally:
            for remote in staged:
                self._transport.exec_ok(f"rm -f {shlex.quote(remote)}", effect=Effect.DESTRUCTIVE)

        # `pm install` reports failure on stdout and the transport reads no
        # exit status, so re-reading the package list is the only honest
        # evidence that anything happened.
        if not actions.installed_version(self._transport, package_name):
            raise TransportError(f"Install reported no error but {package_name} is not present afterwards", target=self._transport.target)

    # -- Internal ----------------------------------------------------------

    def _apk_paths(self, package: str) -> tuple[str, ...]:
        """RETURNS: tuple[str, ...]: Every APK path `pm path` reports, base first."""
        output = self._transport.exec_ok(f"pm path {shlex.quote(package)}", effect=Effect.READ)
        return tuple(line.partition(":")[2].strip() for line in output.splitlines() if line.strip().startswith("package:"))


def _package_names(output: str) -> list[str]:
    """RETURNS: list[str]: Package names from a `pm list packages` dump, in the order reported."""
    names = []
    for line in output.splitlines():
        name = line.partition(":")[2].strip()
        if line.strip().startswith("package:") and name:
            names.append(name)
    return names


def apk_filename(package: str, remote: str, index: int) -> str:
    """Name a pulled APK so the set round-trips.

    The on-device basename is not unique across packages — every base APK is
    called `base.apk` — and the split names carry the randomised install
    directory's meaning nowhere. Prefixing the package and the index keeps the
    order `pm install-multiple` needs, in the filename itself.

    **RETURNS:**
        `str`: A filename unique within one snapshot.  <br>
    """
    leaf = posixpath.basename(remote) or "base.apk"
    return f"{package}-{index:02d}-{leaf}"


def _install_timeout(apks: Sequence[Path]) -> float:
    """Scale the install timeout by payload size.

    A flat timeout is how this project's predecessor silently truncated large
    transfers on slower devices; the same reasoning applies to an install the
    device has to verify and optimise.

    **RETURNS:**
        `float`: Seconds, floored at three minutes.  <br>
    """
    total = sum(apk.stat().st_size for apk in apks)
    return max(180.0, total / 500_000.0)
