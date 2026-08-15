"""The SSH transport, against a stubbed SSH client.

No test here opens a socket. The paramiko client is the external boundary and
is stubbed at it; everything this project owns — status handling, sudo
wrapping, truncation detection, `df` parsing — is exercised for real.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fleetctl.core.effects import Capability, Effect
from fleetctl.core.errors import CommandFailedError, ConfigError, DeviceUnauthorizedError, TransportError
from fleetctl.packs.posix.transport import SshSettings, SshTransport


class _Channel:
    """Stands in for paramiko's exec channel."""

    def __init__(self, status: int) -> None:
        self._status = status

    def recv_exit_status(self) -> int:
        return self._status

    def settimeout(self, value: float) -> None:
        """Accepted and ignored; there is no real socket behind this."""


class _Stream:
    def __init__(self, payload: str, status: int = 0) -> None:
        self._payload = payload
        self.channel = _Channel(status)

    def read(self) -> bytes:
        return self._payload.encode("utf-8")


class _StubSftp:
    """Stands in for paramiko's SFTPClient, backed by the local filesystem."""

    def __init__(self, *, reported_size: int | None = None, fail: bool = False) -> None:
        self.reported_size = reported_size
        self.fail = fail
        self.uploaded: list[tuple[str, str]] = []
        self.closed = False

    def put(self, local: str, remote: str) -> None:
        if self.fail:
            raise OSError("permission denied")
        self.uploaded.append((local, remote))
        self._last_local = local

    def get(self, remote: str, local: str) -> None:
        if self.fail:
            raise OSError("no such file")
        Path(local).write_bytes(b"downloaded")

    def stat(self, remote: str) -> Any:
        size = self.reported_size if self.reported_size is not None else Path(self._last_local).stat().st_size
        return type("Stat", (), {"st_size": size})()

    def get_channel(self) -> _Channel:
        return _Channel(0)

    def close(self) -> None:
        self.closed = True


class _StubClient:
    """Stands in for paramiko's SSHClient."""

    def __init__(self, responses: dict[str, tuple[str, str, int]] | None = None, sftp: _StubSftp | None = None) -> None:
        self.responses = responses or {}
        self.sftp = sftp or _StubSftp()
        self.commands: list[str] = []
        self.closed = False

    def exec_command(self, command: str, timeout: float | None = None) -> tuple[None, _Stream, _Stream]:
        self.commands.append(command)
        out, err, status = self.responses.get(command, ("", "not scripted", 127))
        return None, _Stream(out, status), _Stream(err)

    def open_sftp(self) -> _StubSftp:
        return self.sftp

    def close(self) -> None:
        self.closed = True


def _connected(transport: SshTransport, client: _StubClient) -> SshTransport:
    """Attach a stub client, standing in for a completed `connect()`."""
    transport._client = client  # noqa: SLF001
    return transport


def test_exec_returns_stripped_output() -> None:
    # Arrange
    client = _StubClient({"uname -r": ("6.1.0-18-amd64\n", "", 0)})
    transport = _connected(SshTransport("192.168.1.70", SshSettings(user="ops")), client)

    # Act
    result = transport.exec("uname -r", effect=Effect.READ)

    # Assert
    assert result == "6.1.0-18-amd64"


def test_a_nonzero_exit_raises_rather_than_returning_empty() -> None:
    """An empty string would be indistinguishable from a command that ran and
    printed nothing — the difference between failure and success."""
    # Arrange
    client = _StubClient({"false": ("", "it broke", 1)})
    transport = _connected(SshTransport("192.168.1.70", SshSettings(user="ops")), client)

    # Act / Assert
    with pytest.raises(CommandFailedError) as caught:
        transport.exec("false")
    assert caught.value.exit_code == 1
    assert caught.value.target == "192.168.1.70"


def test_exec_ok_swallows_a_failure() -> None:
    # Arrange
    transport = _connected(SshTransport("192.168.1.70", SshSettings(user="ops")), _StubClient({"false": ("", "no", 1)}))

    # Act / Assert
    assert transport.exec_ok("false") == ""


def test_sudo_is_non_interactive_when_a_pack_asks_for_it() -> None:
    """A password prompt on a non-interactive channel hangs until the timeout
    instead of failing, so the `-n` is load-bearing."""
    # Arrange
    client = _StubClient({"sudo -n systemctl reboot": ("", "", 0)})
    transport = _connected(SshTransport("192.168.1.70", SshSettings(user="ops"), use_sudo=True), client)

    # Act
    transport.exec("systemctl reboot", effect=Effect.DESTRUCTIVE)

    # Assert
    assert client.commands == ["sudo -n systemctl reboot"]


def test_commands_are_not_elevated_by_default() -> None:
    # Arrange
    client = _StubClient({"id -u": ("1000", "", 0)})
    transport = _connected(SshTransport("192.168.1.70", SshSettings(user="ops")), client)

    # Act
    transport.exec("id -u", effect=Effect.READ)

    # Assert
    assert client.commands == ["id -u"]


def test_put_reports_the_bytes_that_landed(tmp_path: Path) -> None:
    # Arrange
    payload = tmp_path / "build.tar.gz"
    payload.write_bytes(b"x" * 2048)
    client = _StubClient()
    transport = _connected(SshTransport("192.168.1.70", SshSettings(user="ops")), client)

    # Act
    written = transport.put(payload, "/tmp/build.tar.gz")

    # Assert
    assert written == 2048
    assert client.sftp.uploaded == [(str(payload), "/tmp/build.tar.gz")]


def test_a_truncated_upload_is_caught_rather_than_reported_as_success(tmp_path: Path) -> None:
    """This is the exact failure the predecessor hit over ADB: the transfer
    returns cleanly and the file on the far side is short."""
    # Arrange
    payload = tmp_path / "build.tar.gz"
    payload.write_bytes(b"x" * 2048)
    transport = _connected(
        SshTransport("192.168.1.70", SshSettings(user="ops")),
        _StubClient(sftp=_StubSftp(reported_size=64)),
    )

    # Act / Assert
    with pytest.raises(TransportError, match="truncated"):
        transport.put(payload, "/tmp/build.tar.gz")


def test_a_failed_upload_raises_a_transport_error(tmp_path: Path) -> None:
    # Arrange
    payload = tmp_path / "build.tar.gz"
    payload.write_bytes(b"x")
    transport = _connected(SshTransport("192.168.1.70", SshSettings(user="ops")), _StubClient(sftp=_StubSftp(fail=True)))

    # Act / Assert
    with pytest.raises(TransportError, match="upload"):
        transport.put(payload, "/tmp/build.tar.gz")


def test_get_writes_the_file_and_creates_its_parent(tmp_path: Path) -> None:
    # Arrange
    destination = tmp_path / "nested" / "profile.tar.gz"
    transport = _connected(SshTransport("192.168.1.70", SshSettings(user="ops")), _StubClient())

    # Act
    read = transport.get("/tmp/profile.tar.gz", destination)

    # Assert
    assert destination.read_bytes() == b"downloaded"
    assert read == len(b"downloaded")


def test_a_failed_download_raises_a_transport_error(tmp_path: Path) -> None:
    # Arrange
    transport = _connected(SshTransport("192.168.1.70", SshSettings(user="ops")), _StubClient(sftp=_StubSftp(fail=True)))

    # Act / Assert
    with pytest.raises(TransportError, match="download"):
        transport.get("/tmp/missing.tar.gz", tmp_path / "out.tar.gz")


def test_free_bytes_reads_the_available_column() -> None:
    # Arrange
    df = "Filesystem 1K-blocks Used Available Use% Mounted on\n/dev/sda1 100000000 40000000 2097152 40% /"
    transport = _connected(SshTransport("192.168.1.70", SshSettings(user="ops")), _StubClient({"df -k /tmp": (df, "", 0)}))

    # Act / Assert
    assert transport.free_bytes("/tmp") == 2097152 * 1024


@pytest.mark.parametrize("output", ["", "Filesystem 1K-blocks Used Available Use% Mounted on", "garbage from a broken shell"])
def test_free_bytes_reports_zero_rather_than_guessing(output: str) -> None:
    """A wrong number here would let a restore start with no room."""
    # Arrange
    transport = _connected(SshTransport("192.168.1.70", SshSettings(user="ops")), _StubClient({"df -k /tmp": (output, "", 0)}))

    # Act / Assert
    assert transport.free_bytes("/tmp") == 0


def test_close_is_idempotent(tmp_path: Path) -> None:
    # Arrange
    client = _StubClient()
    transport = _connected(SshTransport("192.168.1.70", SshSettings(user="ops")), client)
    transport.get("/tmp/x", tmp_path / "x")

    # Act
    transport.close()
    transport.close()

    # Assert
    assert client.closed is True
    assert client.sftp.closed is True


def test_a_transfer_on_an_unopened_session_fails_loudly(tmp_path: Path) -> None:
    # Arrange
    payload = tmp_path / "x"
    payload.write_bytes(b"x")
    transport = SshTransport("192.168.1.70", SshSettings(user="ops"))

    # Act / Assert
    with pytest.raises(TransportError, match="not open"):
        transport.put(payload, "/tmp/x")


def test_is_online_is_false_when_nothing_is_listening() -> None:
    """Port 1 on the loopback interface, so this stays local and closed."""
    # Arrange
    transport = SshTransport("127.0.0.1", SshSettings(user="ops", port=1))

    # Act / Assert
    assert transport.is_online(timeout_s=0.25) is False


def test_the_transport_declares_only_what_ssh_actually_provides() -> None:
    """Over-declaring is what fails mid-run on real hardware. Package
    management and system settings are distribution-specific."""
    # Act
    capabilities = SshTransport("192.168.1.70", SshSettings(user="ops")).capabilities()

    # Assert
    assert Capability.EXEC in capabilities
    assert Capability.FILES in capabilities
    assert Capability.APPS not in capabilities
    assert Capability.SETTINGS not in capabilities


def test_the_target_is_the_address_it_was_given() -> None:
    # Act / Assert
    assert SshTransport("192.168.1.70", SshSettings(user="ops")).target == "192.168.1.70"


def test_an_unknown_host_is_not_reported_as_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    """A sweep meets hosts that are not ours. `DeviceUnauthorizedError` means
    "our device refused our credentials" and puts an entry in the inventory —
    a stranger with port 22 open must not land there."""
    # Arrange
    import paramiko

    from fleetctl.packs.posix.transport import UnknownHostKey

    def _raise(*args: object, **kwargs: object) -> None:
        raise UnknownHostKey("192.168.1.70")

    monkeypatch.setattr(paramiko.SSHClient, "connect", _raise)
    transport = SshTransport("192.168.1.70", SshSettings(user="ops"))

    # Act / Assert
    with pytest.raises(TransportError, match="not in known_hosts") as caught:
        transport.connect()
    assert not isinstance(caught.value, DeviceUnauthorizedError)


def test_a_refused_credential_is_still_reported_as_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    """The host key was known, so this is a host we expect — worth surfacing."""
    # Arrange
    import paramiko

    def _raise(*args: object, **kwargs: object) -> None:
        raise paramiko.AuthenticationException("bad password")

    monkeypatch.setattr(paramiko.SSHClient, "connect", _raise)
    transport = SshTransport("192.168.1.70", SshSettings(user="ops"))

    # Act / Assert
    with pytest.raises(DeviceUnauthorizedError):
        transport.connect()


@pytest.mark.parametrize("key", ["key_path", "known_hosts"])
def test_a_relative_path_is_rejected_at_config_load(key: str) -> None:
    """Nothing here can say what a relative path is relative *to* — the CWD
    belongs to whoever launched the process. A relative `known_hosts` reached a
    live fleet through the HA options form and failed as a bare
    `FileNotFoundError`, which read as the device being unreachable."""
    # Act / Assert
    with pytest.raises(ConfigError, match="must be an absolute path") as caught:
        SshSettings.from_mapping({"user": "ops", key: ".ssh/deploy_key"})

    assert caught.value.key == f"ssh.{key}"


@pytest.mark.parametrize("key", ["key_path", "known_hosts"])
def test_an_absolute_path_survives_config_load(key: str) -> None:
    # Act
    settings = SshSettings.from_mapping({"user": "ops", key: "/keys/thing"})

    # Assert
    assert getattr(settings, key) == Path("/keys/thing")


def test_a_home_relative_path_is_expanded_not_rejected() -> None:
    """`~` has an unambiguous meaning, so it is expanded rather than refused."""
    # Act
    settings = SshSettings.from_mapping({"user": "ops", "known_hosts": "~/.ssh/known_hosts"})

    # Assert
    assert settings.known_hosts is not None
    assert settings.known_hosts.is_absolute()
    assert "~" not in str(settings.known_hosts)


@pytest.mark.parametrize("key", ["key_path", "known_hosts"])
def test_an_unset_path_stays_none(key: str) -> None:
    """Blank is how a deployment asks for the default, so it must not raise."""
    # Act
    settings = SshSettings.from_mapping({"user": "ops", key: ""})

    # Assert
    assert getattr(settings, key) is None


def test_an_unreadable_known_hosts_file_is_reported_as_a_transport_error(tmp_path: Path) -> None:
    """`load_host_keys` raises before `connect` is ever called. Unguarded, that
    escaped as a bare `FileNotFoundError` — an exception type no caller of this
    method is written to expect."""
    # Arrange
    missing = tmp_path / "nonexistent" / "known_hosts"
    transport = SshTransport("192.168.1.70", SshSettings(user="ops", known_hosts=missing))

    # Act / Assert
    with pytest.raises(TransportError, match="Could not read known_hosts") as caught:
        transport.connect()

    assert caught.value.target == "192.168.1.70"
