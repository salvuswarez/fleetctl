"""SSH transport: the real hardware path for POSIX hosts."""

from __future__ import annotations

import logging
import shlex
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from fleetctl.core.config.secrets import Secret
from fleetctl.core.effects import Capability, Effect
from fleetctl.core.errors import CommandFailedError, DeviceUnauthorizedError, TransportError

LOGGER = logging.getLogger(__name__)

SSH_PORT = 22
_CONNECT_TIMEOUT_S = 15.0
_SHELL_TIMEOUT_S = 60.0
# Covers a worst-case SFTP transfer rather than a single round trip.
_TRANSFER_TIMEOUT_S = 3600.0

# No APPS or SETTINGS: package management and system settings differ per
# distribution, so a host pack that implements them declares them itself.
# Over-declaring here would fail mid-run on real hardware.
CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.REACH,
        Capability.FACTS,
        Capability.EXEC,
        Capability.FILES,
        Capability.POWER,
        Capability.CLEANUP,
    }
)


class UnknownHostKey(Exception):
    """Raised by the host-key policy when a host is not in `known_hosts`.

    Distinct from an authentication failure. A sweep meets hosts that are not
    ours at all — a NAS, a phone — and an unrecognised key means "never seen
    this", not "our device rejected our credentials". Conflating them recorded
    every stranger with an open port as a device awaiting key approval.
    """


def _reject_unknown_host(paramiko_module: Any) -> Any:
    """Build a host-key policy that refuses anything absent from `known_hosts`.

    Defined here rather than at module scope because paramiko is imported
    lazily, matching how the ADB packs treat `adb_shell`.

    Deliberately not `AutoAddPolicy`: silently trusting a new key on a fleet
    tool turns a man-in-the-middle into a no-op.

    **RETURNS:**
        `MissingHostKeyPolicy`: A policy raising `UnknownHostKey`.  <br>
    """

    class _Policy(paramiko_module.MissingHostKeyPolicy):  # type: ignore[misc]
        def missing_host_key(self, client: Any, hostname: str, key: Any) -> None:
            """Refuse a host whose key is not already pinned.

            **RAISES:**
                `UnknownHostKey`: Always. A distinct error type on purpose — a transport that reports "credential refused" and "host not in known_hosts" identically lets discovery read a stranger as a fleet device.  <br>
            """
            raise UnknownHostKey(hostname)

    return _Policy()


@dataclass(frozen=True, slots=True)
class SshSettings:
    """How to authenticate to a POSIX host.

    Values arrive already resolved — a `!ref` is unwrapped by the composition
    root, never by this transport.

    **PARAMETERS:**
        `user` (str): Login user.  <br>
        `key_path` (Path | None): Private key to authenticate with. Defaults to ``None``, meaning fall back to `password`.  <br>
        `password` (Secret | str): Password, normally a resolved `!ref`. Defaults to ``""``.  <br>
        `port` (int): TCP port. Defaults to `SSH_PORT`.  <br>
        `known_hosts` (Path | None): Known-hosts file to verify the host key against. Defaults to ``None``, meaning the system default is loaded and an unknown host is **rejected**.  <br>
    """

    user: str = ""
    key_path: Path | None = None
    password: Secret | str = ""
    port: int = SSH_PORT
    known_hosts: Path | None = None

    def reveal_password(self) -> str:
        """RETURNS: str: The password value, unwrapped only here at the edge."""
        return self.password.reveal() if isinstance(self.password, Secret) else str(self.password)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> SshSettings:
        """RETURNS: SshSettings: Settings read from a device's `vars.ssh` block."""
        key = data.get("key_path")
        hosts = data.get("known_hosts")
        return cls(
            user=str(data.get("user", "")),
            key_path=Path(str(key)).expanduser() if key else None,
            password=data.get("password", ""),
            port=int(data.get("port", SSH_PORT)),
            known_hosts=Path(str(hosts)).expanduser() if hosts else None,
        )


class SshTransport:
    """A `Transport` over SSH, for any host with a POSIX shell.

    **PARAMETERS:**
        `address` (str): Host address.  <br>
        `settings` (SshSettings): Login user and credential.  <br>
        `use_sudo` (bool): Prefix privileged commands with ``sudo -n``. Defaults to ``False``.  <br>
    """

    def __init__(self, address: str, settings: SshSettings, *, use_sudo: bool = False) -> None:
        self._address = address
        self._settings = settings
        self._use_sudo = use_sudo
        self._client: Any = None
        self._sftp: Any = None

    @property
    def target(self) -> str:
        """RETURNS: str: The host address this transport talks to."""
        return self._address

    def capabilities(self) -> frozenset[Capability]:
        """RETURNS: frozenset[Capability]: What SSH can do on a generic POSIX host."""
        return CAPABILITIES

    def connect(self) -> None:
        """Open the SSH session.

        **RAISES:**
            `DeviceUnauthorizedError`: If the host key is known but the credential was refused — an expected host, worth acting on.  <br>
            `TransportError`: If the host is unreachable, absent from `known_hosts`, or the handshake failed.  <br>
        """
        import paramiko

        client = paramiko.SSHClient()
        if self._settings.known_hosts is not None:
            client.load_host_keys(str(self._settings.known_hosts))
        else:
            client.load_system_host_keys()
        client.set_missing_host_key_policy(_reject_unknown_host(paramiko))

        try:
            client.connect(
                hostname=self._address,
                port=self._settings.port,
                username=self._settings.user,
                key_filename=str(self._settings.key_path) if self._settings.key_path else None,
                password=self._settings.reveal_password() or None,
                timeout=_CONNECT_TIMEOUT_S,
                allow_agent=False,
                look_for_keys=False,
            )
        except UnknownHostKey as exc:
            # Not "unauthorized": a sweep meets hosts that are not ours, and
            # recording each one as awaiting key approval buries the devices
            # that genuinely are.
            raise TransportError(f"{self._address} is not in known_hosts", target=self._address) from exc
        except paramiko.AuthenticationException as exc:
            # Host key is known, so this host is one we expect — the
            # credentials were refused, and that is worth acting on.
            raise DeviceUnauthorizedError(self._address, str(exc)) from exc
        except paramiko.SSHException as exc:
            raise TransportError(f"SSH handshake with {self._address} failed: {exc}", target=self._address) from exc
        except (OSError, socket.error) as exc:
            raise TransportError(f"Could not reach {self._address} over SSH: {exc}", target=self._address) from exc

        self._client = client
        LOGGER.debug("SSH session established to %s as %s", self._address, self._settings.user)

    def is_online(self, timeout_s: float = 3.0) -> bool:
        """RETURNS: bool: Whether the host accepts a TCP connection on its SSH port."""
        try:
            with socket.create_connection((self._address, self._settings.port), timeout=timeout_s):
                return True
        except OSError:
            return False

    def exec(self, command: str, *, effect: Effect = Effect.MUTATING, timeout_s: float | None = None) -> str:
        """Run a command, raising if it failed.

        **RETURNS:**
            `str`: Stdout, stripped.  <br>

        **RAISES:**
            `CommandFailedError`: If the command exited non-zero or the channel broke. Never returned as an empty string, so a caller cannot mistake failure for success.  <br>
        """
        stdout, stderr, status = self._run(command, timeout_s)
        if status != 0:
            raise CommandFailedError(
                stderr.strip() or f"command exited {status}",
                target=self._address,
                command=command,
                exit_code=status,
            )
        return stdout.strip()

    def exec_ok(self, command: str, *, effect: Effect = Effect.MUTATING, timeout_s: float | None = None) -> str:
        """RETURNS: str: Stdout, or `""` if the command failed."""
        try:
            return self.exec(command, effect=effect, timeout_s=timeout_s)
        except CommandFailedError:
            return ""

    def put(self, local_path: Path, remote_path: str, *, effect: Effect = Effect.MUTATING) -> int:
        """Upload a file over SFTP and verify its size.

        **RETURNS:**
            `int`: Bytes written.  <br>

        **RAISES:**
            `TransportError`: If the transfer failed or the remote size did not match.  <br>
        """
        expected = local_path.stat().st_size
        try:
            self._channel().put(str(local_path), remote_path)
            written = int(self._channel().stat(remote_path).st_size or 0)
        except OSError as exc:
            raise TransportError(f"SFTP upload to {remote_path} failed: {exc}", target=self._address) from exc

        # A silently truncated upload is the exact failure the predecessor hit
        # over ADB. Cheap to rule out, and catastrophic to miss.
        if written != expected:
            raise TransportError(f"Upload to {remote_path} truncated: sent {expected} bytes, {written} landed", target=self._address)
        return written

    def get(self, remote_path: str, local_path: Path) -> int:
        """Download a file over SFTP.

        **RETURNS:**
            `int`: Bytes read.  <br>

        **RAISES:**
            `TransportError`: If the transfer failed.  <br>
        """
        local_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._channel().get(remote_path, str(local_path))
        except OSError as exc:
            raise TransportError(f"SFTP download of {remote_path} failed: {exc}", target=self._address) from exc
        return local_path.stat().st_size

    def free_bytes(self, remote_path: str) -> int:
        """RETURNS: int: Free bytes on the filesystem holding `remote_path`, or ``0`` if it could not be determined."""
        output = self.exec_ok(f"df -k {shlex.quote(remote_path)}", effect=Effect.READ)
        rows = output.splitlines()
        if len(rows) < 2:
            return 0
        columns = rows[-1].split()
        if len(columns) >= 3 and columns[-3].isdigit():
            return int(columns[-3]) * 1024
        return 0

    def close(self) -> None:
        """Release the SSH session. Idempotent."""
        if self._sftp is not None:
            self._sftp.close()
            self._sftp = None
        if self._client is not None:
            self._client.close()
            self._client = None

    def _run(self, command: str, timeout_s: float | None) -> tuple[str, str, int]:
        """RETURNS: tuple[str, str, int]: Stdout, stderr, and the exit status."""
        if self._client is None:
            raise TransportError(f"SSH session to {self._address} is not open", target=self._address)

        # `sudo -n` never prompts: a password prompt on a non-interactive
        # channel would hang until the timeout instead of failing.
        wrapped = f"sudo -n {command}" if self._use_sudo else command
        try:
            _, stdout, stderr = self._client.exec_command(wrapped, timeout=timeout_s or _SHELL_TIMEOUT_S)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            status = int(stdout.channel.recv_exit_status())
        except (OSError, EOFError) as exc:
            raise CommandFailedError(f"SSH channel failed: {exc}", target=self._address, command=command) from exc
        return out, err, status

    def _channel(self) -> Any:
        """RETURNS: SFTPClient: The SFTP channel, opened on first use."""
        if self._client is None:
            raise TransportError(f"SSH session to {self._address} is not open", target=self._address)
        if self._sftp is None:
            self._sftp = self._client.open_sftp()
            self._sftp.get_channel().settimeout(_TRANSFER_TIMEOUT_S)
        return self._sftp
