"""Exception hierarchy, rooted at one base so callers can catch by layer.

A step catches `TransportError` without knowing whether it was talking ADB
or SSH. Domain context lives on the exception as attributes rather than only
in the message string, so a handler can branch on it.
"""

from __future__ import annotations


class FleetError(Exception):
    """Base for every error raised by fleetctl."""


class TransportError(FleetError):
    """A device could not be reached, or an operation against it failed.

    **PARAMETERS:**
        `message` (str): Human-readable description.  <br>
        `target` (str): Address or id of the device involved.  <br>
    """

    def __init__(self, message: str, *, target: str = "") -> None:
        super().__init__(message)
        self.target = target


class CommandFailedError(TransportError):
    """A command ran but reported failure.

    Deliberately distinct from "the command ran and produced no output" — the
    predecessor collapsed both to `""`, which is how a dropped connection
    during a destructive command could look identical to success.

    **PARAMETERS:**
        `message` (str): Human-readable description.  <br>
        `target` (str): Address or id of the device involved.  <br>
        `command` (str): The command that failed.  <br>
        `exit_code` (int | None): Exit status, when the transport reports one.  <br>
    """

    def __init__(self, message: str, *, target: str = "", command: str = "", exit_code: int | None = None) -> None:
        super().__init__(message, target=target)
        self.command = command
        self.exit_code = exit_code


class DeviceUnauthorizedError(TransportError):
    """The device is reachable but rejected our credentials.

    Deliberately distinct from a plain `TransportError`: an address with
    nothing listening and an address that refused the key look identical in a
    scan's output, but the first means "not a device I manage" and the second
    means "approve the prompt on the screen". Only one of those is actionable.

    **PARAMETERS:**
        `target` (str): Address or id of the device involved.  <br>
        `detail` (str): What the underlying transport reported.  <br>
    """

    def __init__(self, target: str, detail: str = "") -> None:
        super().__init__(f"{target} is reachable but did not authorize this key" + (f": {detail}" if detail else ""), target=target)
        self.detail = detail


class UnsupportedCapabilityError(TransportError):
    """A transport was asked for something it does not implement.

    Raised rather than silently no-oping so an over-declared capability fails
    loudly at the call site instead of appearing to succeed.

    **PARAMETERS:**
        `capability` (str): The capability that was required.  <br>
        `target` (str): Address or id of the device involved.  <br>
    """

    def __init__(self, capability: str, *, target: str = "") -> None:
        super().__init__(f"Transport for {target or 'device'} does not support {capability!r}", target=target)
        self.capability = capability


class ArtifactError(FleetError):
    """An artifact could not be stored, retrieved, or referenced.

    **PARAMETERS:**
        `message` (str): Human-readable description.  <br>
        `ref` (str): The artifact reference involved, when known.  <br>
    """

    def __init__(self, message: str, *, ref: str = "") -> None:
        super().__init__(message)
        self.ref = ref


class ConfigError(FleetError):
    """Configuration was missing, malformed, or failed validation.

    **PARAMETERS:**
        `message` (str): Human-readable description.  <br>
        `key` (str): Dotted path of the offending config key, when known.  <br>
    """

    def __init__(self, message: str, *, key: str = "") -> None:
        super().__init__(message)
        self.key = key


class SecretResolutionError(ConfigError):
    """A `!ref` pointer could not be resolved to a value.

    **PARAMETERS:**
        `reference` (str): The unresolved reference, e.g. ``env:FLEETCTL_SMB_PASS``.  <br>
    """

    def __init__(self, reference: str) -> None:
        super().__init__(f"Could not resolve secret reference {reference!r}", key=reference)
        self.reference = reference


class OperationCancelled(FleetError):
    """Raised inside a step body when its operation has been cancelled."""
