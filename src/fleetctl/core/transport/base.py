"""The transport protocols."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from fleetctl.core.effects import Capability, Effect


@runtime_checkable
class Reachable(Protocol):
    """Can answer whether a target is responding."""

    @property
    def target(self) -> str:
        """RETURNS: str: Address or id this transport talks to, for logs and audit records."""

    def is_online(self, timeout_s: float = 3.0) -> bool:
        """Check whether the target is accepting connections.

        **PARAMETERS:**
            `timeout_s` (float, optional): Connect timeout in seconds. Defaults to ``3.0``.  <br>

        **RETURNS:**
            `bool`: True when the target responded.  <br>
        """


@runtime_checkable
class CommandRunner(Protocol):
    """Can run a command on a target and return its output."""

    def exec(self, command: str, *, effect: Effect = Effect.MUTATING, timeout_s: float | None = None) -> str:
        """Run a command, raising if it could not be executed.

        **PARAMETERS:**
            `command` (str): Command to run on the target.  <br>
            `effect` (Effect, optional): How much this command changes. Drives audit routing and policy. Defaults to `Effect.MUTATING`, so an unlabelled command is recorded rather than silently dropped.  <br>
            `timeout_s` (float | None, optional): Per-call timeout. Defaults to ``None``, meaning the transport's own default. Pass an explicit value for anything whose duration scales with data size.  <br>

        **RETURNS:**
            `str`: Command output, stripped.  <br>

        **RAISES:**
            `CommandFailedError`: If the command could not be executed or reported failure. Never returned as an empty string, so a caller cannot mistake failure for success.  <br>
        """

    def exec_ok(self, command: str, *, effect: Effect = Effect.MUTATING, timeout_s: float | None = None) -> str:
        """Run a command, returning `""` on failure instead of raising.

        **PARAMETERS:**
            `command` (str): Command to run on the target.  <br>
            `effect` (Effect, optional): How much this command changes. Defaults to `Effect.MUTATING`.  <br>
            `timeout_s` (float | None, optional): Per-call timeout. Defaults to ``None``.  <br>

        **RETURNS:**
            `str`: Command output, or ``""`` if the command failed.  <br>
        """


@runtime_checkable
class FileTransfer(Protocol):
    """Can move files to and from a target."""

    def put(self, local_path: Path, remote_path: str, *, effect: Effect = Effect.MUTATING) -> int:
        """Upload a file to the target.

        **PARAMETERS:**
            `local_path` (Path): File to upload.  <br>
            `remote_path` (str): Destination path on the target.  <br>
            `effect` (Effect, optional): How much this write changes. Defaults to `Effect.MUTATING`.  <br>

        **RETURNS:**
            `int`: Bytes written.  <br>

        **RAISES:**
            `TransportError`: If the transfer failed or could not be verified.  <br>
        """

    def get(self, remote_path: str, local_path: Path) -> int:
        """Download a file from the target.

        **PARAMETERS:**
            `remote_path` (str): Source path on the target.  <br>
            `local_path` (Path): Local destination.  <br>

        **RETURNS:**
            `int`: Bytes read.  <br>

        **RAISES:**
            `TransportError`: If the transfer failed.  <br>
        """

    def free_bytes(self, remote_path: str) -> int:
        """Report free space on the filesystem holding `remote_path`.

        **PARAMETERS:**
            `remote_path` (str): Any path on the filesystem to measure.  <br>

        **RETURNS:**
            `int`: Free bytes, or ``0`` when it could not be determined.  <br>
        """


@runtime_checkable
class Transport(Reachable, CommandRunner, FileTransfer, Protocol):
    """Everything a step may do to a device."""

    def capabilities(self) -> frozenset[Capability]:
        """RETURNS: frozenset[Capability]: What this transport can actually do."""

    def close(self) -> None:
        """Release the underlying connection. Idempotent."""
