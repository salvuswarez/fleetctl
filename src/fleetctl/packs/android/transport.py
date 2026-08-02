"""ADB transport: the real hardware path.

Lives in the Android pack rather than the kernel because ADB *is* Android —
a kernel that knows about it could not stay device-agnostic.

Two behaviours here are not obvious and were both established against real
hardware. Both are load-bearing; neither should be simplified without
re-measuring on a device.

**Uploads go over netcat, not the ADB push protocol.** Measured against a
real Fire TV from both a workstation and Home Assistant: `push()` moved zero
bytes and hung until timeout for anything beyond a few megabytes, and the
destination file was never created. The same host sustained 5-12 MB/s
streaming into an on-device `nc`. `shell()` and `pull()` are unaffected and
are used as-is.

**The listener cannot be backgrounded.** `adb_shell` closes the shell stream
when a command returns, and the device tears down the process group with it,
killing a `&`-backgrounded `nc` before anything connects. `nohup` and
`setsid` do not help. The listener therefore runs on its own connection held
open by a worker thread, and exits naturally when the transfer socket closes.
"""

from __future__ import annotations

import hashlib
import io
import logging
import shlex
import socket
import threading
import time
from pathlib import Path
from typing import Any

from ...core.effects import Capability, Effect
from ...core.errors import CommandFailedError, DeviceUnauthorizedError, TransportError
from .keys import AdbKeyStore

LOGGER = logging.getLogger(__name__)

ADB_PORT = 5555
NC_PORT = 5599
_CHUNK = 262144
_CONNECT_TIMEOUT_S = 30.0
# Only covers the flush after the last byte is sent, not the transfer itself.
_SETTLE_TIMEOUT_S = 120.0
# The listener's command blocks for the whole transfer, so its timeout must
# cover a worst-case upload rather than a single round-trip.
_LISTENER_TIMEOUT_S = 3600.0
_SHELL_TIMEOUT_S = 60.0
_TRANSFER_TIMEOUT_S = 180.0

CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.REACH,
        Capability.FACTS,
        Capability.EXEC,
        Capability.FILES,
        Capability.APPS,
        Capability.SETTINGS,
        Capability.POWER,
        Capability.STATE,
        Capability.CLEANUP,
    }
)


class AdbTransport:
    """One ADB connection to a device, held open for a whole operation.

    Held open deliberately: the auth handshake is expensive, and the
    predecessor paid roughly one per command until this was fixed.

    **PARAMETERS:**
        `address` (str): Device IPv4 address.  <br>
        `keys` (AdbKeyStore): Shared signer cache.  <br>
        `port` (int): ADB port. Defaults to 5555.  <br>
        `use_netcat` (bool): Stream uploads through an on-device listener rather than the ADB push protocol. Defaults to ``True``; set from a pack's quirks.  <br>
        `shell_timeout_s` (float): Default per-command timeout.  <br>
        `transfer_timeout_s` (float): Default timeout for transfers, which must cover a whole archive rather than one round-trip.  <br>
    """

    def __init__(
        self,
        address: str,
        keys: AdbKeyStore,
        *,
        port: int = ADB_PORT,
        use_netcat: bool = True,
        shell_timeout_s: float = _SHELL_TIMEOUT_S,
        transfer_timeout_s: float = _TRANSFER_TIMEOUT_S,
    ) -> None:
        self._address = address
        self._keys = keys
        self._port = port
        self._use_netcat = use_netcat
        self._shell_timeout_s = shell_timeout_s
        self._transfer_timeout_s = transfer_timeout_s
        self._device: Any = None

    @property
    def target(self) -> str:
        """RETURNS: str: The device address."""
        return self._address

    def capabilities(self) -> frozenset[Capability]:
        """RETURNS: frozenset[Capability]: Everything ADB can do."""
        return CAPABILITIES

    def __enter__(self) -> AdbTransport:
        self.connect()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def connect(self) -> None:
        """Open the connection and complete the auth handshake.

        **RAISES:**
            `TransportError`: If the host is not listening or auth failed. Raised rather than allowed to escape as a socket error, because a subnet sweep hits mostly non-devices and one of them must not abort the scan.  <br>
        """
        from adb_shell.adb_device import AdbDeviceTcp

        # Checked *before* the handshake, not after. A failed handshake can
        # leave the port briefly unusable, so probing afterwards would report
        # a device that refused the key as simply absent, at random.
        was_listening = self.is_online(timeout_s=2.0)
        try:
            device = AdbDeviceTcp(self._address, self._port, default_transport_timeout_s=self._shell_timeout_s)
            device.connect(rsa_keys=[self._keys.signer(target=self._address)], auth_timeout_s=10.0)
        except Exception as exc:
            # The port answering while the handshake fails means the device is
            # there and said no — a different problem from an empty address,
            # and the only one the user can act on.
            if was_listening:
                raise DeviceUnauthorizedError(self._address, str(exc)) from exc
            raise TransportError(f"ADB connect failed for {self._address}: {exc}", target=self._address) from exc
        self._device = device

    def close(self) -> None:
        """Close the connection. Idempotent."""
        if self._device is None:
            return
        try:
            self._device.close()
        except Exception:
            LOGGER.debug("Error closing ADB connection to %s", self._address, exc_info=True)
        self._device = None

    def is_online(self, timeout_s: float = 3.0) -> bool:
        """RETURNS: bool: Whether the device accepts a TCP connection on the ADB port."""
        try:
            with socket.create_connection((self._address, self._port), timeout=timeout_s):
                return True
        except OSError:
            return False

    def exec(self, command: str, *, effect: Effect = Effect.MUTATING, timeout_s: float | None = None) -> str:
        """Run a command, raising if it could not be executed.

        **RAISES:**
            `CommandFailedError`: If the command could not be run. Never returned as an empty string — a dropped connection during a destructive command must not look like success.  <br>
        """
        timeout = timeout_s if timeout_s is not None else self._shell_timeout_s
        try:
            output = self._require_device().shell(command, transport_timeout_s=timeout, read_timeout_s=timeout)
        except Exception as exc:
            raise CommandFailedError(f"ADB command failed on {self._address}: {exc}", target=self._address, command=command) from exc
        return output.strip() if output else ""

    def exec_ok(self, command: str, *, effect: Effect = Effect.MUTATING, timeout_s: float | None = None) -> str:
        """RETURNS: str: Command output, or ``""`` if it failed."""
        try:
            return self.exec(command, effect=effect, timeout_s=timeout_s)
        except CommandFailedError as exc:
            LOGGER.debug("Command failed on %s, continuing: %s", self._address, exc)
            return ""

    def get(self, remote_path: str, local_path: Path) -> int:
        """Pull a file from the device.

        **RAISES:**
            `TransportError`: If the pull failed.  <br>
        """
        try:
            buffer = io.BytesIO()
            self._require_device().pull(remote_path, buffer, transport_timeout_s=self._transfer_timeout_s, read_timeout_s=self._transfer_timeout_s)
        except Exception as exc:
            raise TransportError(f"ADB pull failed for {remote_path} on {self._address}: {exc}", target=self._address) from exc
        payload = buffer.getvalue()
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(payload)
        return len(payload)

    def free_bytes(self, remote_path: str) -> int:
        """RETURNS: int: Free bytes on the filesystem holding `remote_path`, or 0 if `df` output could not be parsed."""
        output = self.exec_ok(f"df -k {shlex.quote(remote_path)}", effect=Effect.READ)
        lines = output.splitlines()
        if len(lines) < 2:
            return 0
        for value in reversed(lines[-1].split()):
            if value.isdigit():
                return int(value) * 1024
        return 0

    def put(self, local_path: Path, remote_path: str, *, effect: Effect = Effect.MUTATING) -> int:
        """Upload a file and verify it landed intact.

        The digest check is not optional. `nc` exits as soon as it sees the
        connection close and drops whatever is still buffered, so a naive
        send loses its tail — transfers arrived 8-24 KB short. The digest is
        what turns a short write into an error rather than a corrupt deploy.

        **RETURNS:**
            `int`: Bytes uploaded.  <br>

        **RAISES:**
            `TransportError`: If the listener never started, the stream failed, or the digest did not match.  <br>
        """
        size = local_path.stat().st_size
        expected = _file_md5(local_path)
        quoted = shlex.quote(remote_path)
        self.exec_ok(f"rm -f {quoted}", effect=Effect.DESTRUCTIVE)

        if self._use_netcat:
            self._stream_via_netcat(local_path, remote_path, size)
        else:
            self._push_native(local_path, remote_path)

        actual = self.exec_ok(f"md5sum {quoted}", effect=Effect.READ)[:32]
        if actual != expected:
            landed = self._remote_size(remote_path)
            raise TransportError(
                f"Upload to {self._address}:{remote_path} corrupted: expected md5 {expected} of {size} bytes, got {actual or 'none'} of {landed} bytes",
                target=self._address,
            )
        return size

    def _push_native(self, local_path: Path, remote_path: str) -> None:
        try:
            self._require_device().push(str(local_path), remote_path, transport_timeout_s=self._transfer_timeout_s)
        except Exception as exc:
            raise TransportError(f"ADB push failed for {remote_path} on {self._address}: {exc}", target=self._address) from exc

    def _stream_via_netcat(self, local_path: Path, remote_path: str, size: int) -> None:
        listener = _NetcatListener(self._address, self._keys, self._port, remote_path)
        listener.start()
        try:
            sock = self._connect_to_listener()
            try:
                with open(local_path, "rb") as handle:
                    while chunk := handle.read(_CHUNK):
                        sock.sendall(chunk)
                # Wait for the device-side file to reach full size before
                # closing: closing early is exactly what makes nc drop its tail.
                self._await_size(remote_path, size)
                sock.shutdown(socket.SHUT_WR)
            finally:
                sock.close()
        except OSError as exc:
            raise TransportError(f"Netcat upload to {self._address}:{remote_path} failed: {exc}", target=self._address) from exc
        finally:
            listener.stop()

    def _connect_to_listener(self) -> socket.socket:
        """Connect to the device's listener, retrying while it binds.

        The port is deliberately not probed first: `nc -l` accepts exactly one
        connection, so a probe would consume the listener this upload needs.
        """
        deadline = time.monotonic() + _CONNECT_TIMEOUT_S
        last: OSError | None = None
        while time.monotonic() < deadline:
            try:
                return socket.create_connection((self._address, NC_PORT), timeout=_CONNECT_TIMEOUT_S)
            except OSError as exc:
                last = exc
                time.sleep(0.25)
        raise last or OSError(f"netcat listener never came up on {self._address}:{NC_PORT}")

    def _await_size(self, remote_path: str, size: int) -> None:
        """Block until the device-side file reaches `size`, or time out.

        A timeout is logged rather than raised: `put`'s digest check is the
        authority on whether the transfer actually succeeded.
        """
        deadline = time.monotonic() + _SETTLE_TIMEOUT_S
        landed = -1
        while time.monotonic() < deadline:
            landed = self._remote_size(remote_path)
            if landed >= size:
                return
            time.sleep(0.5)
        LOGGER.warning("Device %s stopped at %d/%d bytes for %s", self._address, landed, size, remote_path)

    def _remote_size(self, remote_path: str) -> int:
        output = self.exec_ok(f"stat -c %s {shlex.quote(remote_path)}", effect=Effect.READ).strip()
        return int(output) if output.isdigit() else -1

    def _require_device(self) -> Any:
        if self._device is None:
            raise TransportError(f"Not connected to {self._address}", target=self._address)
        return self._device


class _NetcatListener:
    """Holds `nc -l` running on the device for the lifetime of one upload."""

    def __init__(self, address: str, keys: AdbKeyStore, port: int, remote_path: str) -> None:
        self._address = address
        self._keys = keys
        self._port = port
        self._remote_path = remote_path
        self._error: Exception | None = None
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"nc-listener-{address}")

    def start(self) -> None:
        """Open the listener's own connection and wait for the transfer."""
        self._thread.start()

    def stop(self) -> None:
        """Wait for the listener to exit now the transfer socket is closed."""
        self._thread.join(timeout=_SETTLE_TIMEOUT_S)
        if self._error is not None:
            LOGGER.debug("Netcat listener on %s ended with: %s", self._address, self._error)

    def _run(self) -> None:
        command = f"toybox nc -l -p {NC_PORT} > {shlex.quote(self._remote_path)}"
        try:
            transport = AdbTransport(self._address, self._keys, port=self._port, use_netcat=False)
            transport.connect()
            try:
                # Blocks for the whole transfer, not one round-trip.
                transport.exec(command, timeout_s=_LISTENER_TIMEOUT_S)
            finally:
                transport.close()
        except Exception as exc:  # noqa: BLE001 - surfaced through put()'s digest check
            self._error = exc


def _file_md5(path: Path) -> str:
    """RETURNS: str: Hex md5 of `path`, read in chunks so a large archive never lands in memory whole."""
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()
