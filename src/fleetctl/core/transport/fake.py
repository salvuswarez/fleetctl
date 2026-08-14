"""An in-memory transport for tests and dry runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from fleetctl.core.effects import Capability, Effect
from fleetctl.core.errors import CommandFailedError, UnsupportedCapabilityError

ALL_CAPABILITIES: frozenset[Capability] = frozenset(Capability)


@dataclass(frozen=True, slots=True)
class RecordedCall:
    """One interaction a `FakeTransport` was asked to perform.

    **PARAMETERS:**
        `kind` (str): One of ``exec``, ``put``, or ``get``.  <br>
        `argument` (str): The command, or the remote path for a transfer.  <br>
        `effect` (Effect): The effect the caller declared.  <br>
    """

    kind: str
    argument: str
    effect: Effect


@dataclass
class FakeTransport:
    """Scripted, in-memory `Transport` implementation.

    **PARAMETERS:**
        `target` (str): Address this transport claims to talk to.  <br>
        `responses` (Mapping[str, str]): Command string to output.  <br>
        `failures` (Mapping[str, str]): Command string to the error message it should fail with.  <br>
        `online` (bool): What `is_online` reports.  <br>
        `supported` (frozenset[Capability]): What `capabilities` reports; calls needing anything absent raise.  <br>
        `free_space` (int): What `free_bytes` reports.  <br>
    """

    target: str = "192.168.1.50"
    responses: Mapping[str, str] = field(default_factory=dict)
    failures: Mapping[str, str] = field(default_factory=dict)
    online: bool = True
    supported: frozenset[Capability] = ALL_CAPABILITIES
    free_space: int = 8 * 1024 * 1024 * 1024
    calls: list[RecordedCall] = field(default_factory=list)
    closed: bool = False

    def capabilities(self) -> frozenset[Capability]:
        """RETURNS: frozenset[Capability]: The configured capability set."""
        return self.supported

    def close(self) -> None:
        """Mark this transport closed. Idempotent."""
        self.closed = True

    def is_online(self, timeout_s: float = 3.0) -> bool:
        """RETURNS: bool: The configured `online` value."""
        return self.online

    def exec(self, command: str, *, effect: Effect = Effect.MUTATING, timeout_s: float | None = None) -> str:
        """Return the scripted output for `command`.

        **RAISES:**
            `UnsupportedCapabilityError`: If `Capability.EXEC` was not configured.  <br>
            `CommandFailedError`: If `command` is scripted to fail, or was never scripted at all.  <br>
        """
        self._require(Capability.EXEC)
        self.calls.append(RecordedCall("exec", command, effect))
        if command in self.failures:
            raise CommandFailedError(self.failures[command], target=self.target, command=command)
        if command not in self.responses:
            raise CommandFailedError(f"FakeTransport has no scripted response for {command!r}", target=self.target, command=command)
        return self.responses[command]

    def exec_ok(self, command: str, *, effect: Effect = Effect.MUTATING, timeout_s: float | None = None) -> str:
        """RETURNS: str: The scripted output, or `""` if the command was scripted to fail or is unknown."""
        try:
            return self.exec(command, effect=effect, timeout_s=timeout_s)
        except CommandFailedError:
            return ""

    def put(self, local_path: Path, remote_path: str, *, effect: Effect = Effect.MUTATING) -> int:
        """Record an upload and report the source file's size.

        **RAISES:**
            `UnsupportedCapabilityError`: If `Capability.FILES` was not configured.  <br>
            `CommandFailedError`: If `remote_path` is scripted to fail.  <br>
        """
        self._require(Capability.FILES)
        self.calls.append(RecordedCall("put", remote_path, effect))
        if remote_path in self.failures:
            raise CommandFailedError(self.failures[remote_path], target=self.target, command=f"put {remote_path}")
        return local_path.stat().st_size

    def get(self, remote_path: str, local_path: Path) -> int:
        """Write the scripted content for `remote_path` to `local_path`.

        **RAISES:**
            `UnsupportedCapabilityError`: If `Capability.FILES` was not configured.  <br>
            `CommandFailedError`: If `remote_path` has no scripted content.  <br>
        """
        self._require(Capability.FILES)
        self.calls.append(RecordedCall("get", remote_path, Effect.READ))
        if remote_path not in self.responses:
            raise CommandFailedError(f"FakeTransport has no scripted content for {remote_path!r}", target=self.target, command=f"get {remote_path}")
        payload = self.responses[remote_path].encode("utf-8")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(payload)
        return len(payload)

    def free_bytes(self, remote_path: str) -> int:
        """RETURNS: int: The configured `free_space` value."""
        return self.free_space

    def commands(self) -> list[str]:
        """RETURNS: list[str]: Every command passed to `exec`/`exec_ok`, in order."""
        return [call.argument for call in self.calls if call.kind == "exec"]

    def _require(self, capability: Capability) -> None:
        if capability not in self.supported:
            raise UnsupportedCapabilityError(capability.value, target=self.target)
