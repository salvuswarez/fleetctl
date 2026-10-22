"""Exception hierarchy, rooted at one base so callers can catch by layer."""

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

    **PARAMETERS:**
        `target` (str): Address or id of the device involved.  <br>
        `detail` (str): What the underlying transport reported.  <br>
    """

    def __init__(self, target: str, detail: str = "") -> None:
        super().__init__(f"{target} is reachable but did not authorize this key" + (f": {detail}" if detail else ""), target=target)
        self.detail = detail


class DeviceHandshakeTimeoutError(DeviceUnauthorizedError):
    """The device answered on its port, but the auth handshake ran out of time.

    Two causes look identical from this side: a key prompt on the device's
    screen that nobody has accepted yet, or a network too slow to finish the
    exchange. Reporting either as "did not authorize this key" sent a deploy's
    reader to the device's settings while every Wi-Fi device on the network
    was answering pings in 300-600ms. Still a `DeviceUnauthorizedError`, so
    discovery goes on flagging a new device that is waiting at its prompt.

    **PARAMETERS:**
        `target` (str): Address or id of the device involved.  <br>
        `timeout_s` (float): How long the handshake was given.  <br>
        `detail` (str): What the underlying transport reported.  <br>
    """

    def __init__(self, target: str, timeout_s: float, detail: str = "") -> None:
        # Skips DeviceUnauthorizedError's message, which is the misleading one.
        TransportError.__init__(
            self,
            f"{target} answered but the auth handshake timed out after {timeout_s:g}s: either it is showing a key prompt "
            f"nobody has accepted, or the network is too slow (check its ping)" + (f" ({detail})" if detail else ""),
            target=target,
        )
        self.detail = detail
        self.timeout_s = timeout_s


class UnsupportedCapabilityError(TransportError):
    """A transport was asked for something it does not implement.

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
