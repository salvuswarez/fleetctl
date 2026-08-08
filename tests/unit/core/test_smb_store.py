"""Tests for SMB settings and backend selection.

The wire protocol is smbprotocol's business; what is tested here is the
decisions around it -- when SMB is used at all, and whether a password can
leak.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fleetctl.core.artifacts.smb import SmbArtifactStore, SmbSettings, _is_transient
from fleetctl.core.artifacts.store import ArtifactStore, LocalArtifactStore
from fleetctl.core.config.secrets import Secret
from fleetctl.core.errors import ArtifactError


def test_the_smb_store_satisfies_the_protocol() -> None:
    assert isinstance(SmbArtifactStore(SmbSettings()), ArtifactStore)


@pytest.mark.parametrize(
    ("settings", "ready"),
    [
        (SmbSettings(host="h", share="s", user="u"), True),
        (SmbSettings(host="h", share="s"), False),
        (SmbSettings(host="h", user="u"), False),
        (SmbSettings(), False),
    ],
)
def test_incomplete_settings_are_not_considered_configured(settings: SmbSettings, ready: bool) -> None:
    assert settings.configured is ready


def test_a_secret_password_is_only_unwrapped_at_the_edge() -> None:
    """It stays masked everywhere else, including in a repr."""
    # Arrange
    settings = SmbSettings(host="h", share="s", user="u", password=Secret("hunter2"))

    # Act / Assert
    assert settings.reveal_password() == "hunter2"
    assert "hunter2" not in repr(settings)
    assert "hunter2" not in str(settings.password)


def test_a_plain_string_password_still_works() -> None:
    assert SmbSettings(password="plain").reveal_password() == "plain"


def test_settings_parse_from_a_fleet_config_block() -> None:
    # Act
    settings = SmbSettings.from_mapping({"host": "192.168.1.50", "share": "Kodi", "root": "fleetctl", "user": "u", "password": "p"})

    # Assert
    assert (settings.host, settings.share, settings.root, settings.user) == ("192.168.1.50", "Kodi", "fleetctl", "u")


def test_using_an_unconfigured_store_says_what_to_set(tmp_path: Path) -> None:
    # Act / Assert
    with pytest.raises(ArtifactError) as caught:
        SmbArtifactStore(SmbSettings()).latest("builds")
    assert "No artifacts" in str(caught.value)


def test_storing_a_missing_file_fails_before_touching_the_network(tmp_path: Path) -> None:
    """No connection is attempted for a file that does not exist."""
    # Arrange
    from fleetctl.core.artifacts.ref import ArtifactRef

    store = SmbArtifactStore(SmbSettings(host="h", share="s", user="u"))

    # Act / Assert
    with pytest.raises(ArtifactError):
        store.put(tmp_path / "absent.tar.gz", ArtifactRef(kind="builds", name="b.tar.gz"))


@pytest.mark.parametrize(
    ("exc", "transient"),
    [(ConnectionError("reset"), True), (BrokenPipeError(), True), (TimeoutError(), True), (ValueError("bad"), False)],
)
def test_only_connection_faults_are_retried(exc: BaseException, transient: bool) -> None:
    """A stale session deserves a reconnect; a real fault should surface."""
    assert _is_transient(exc) is transient


def _store(config: dict[str, Any], tmp_path: Path) -> ArtifactStore:
    from fleetctl.cli.bootstrap import _artifact_store

    return _artifact_store(config, tmp_path)


def test_no_smb_block_means_a_local_store(tmp_path: Path) -> None:
    assert isinstance(_store({}, tmp_path), LocalArtifactStore)


def test_a_complete_smb_block_selects_the_share(tmp_path: Path) -> None:
    # Act
    store = _store({"smb": {"host": "h", "share": "s", "user": "u", "password": "p"}}, tmp_path)

    # Assert
    assert isinstance(store, SmbArtifactStore)


def test_an_incomplete_smb_block_falls_back_rather_than_failing(tmp_path: Path) -> None:
    """An install with a half-written share should still work locally."""
    # Act
    store = _store({"smb": {"host": "h"}}, tmp_path)

    # Assert
    assert isinstance(store, LocalArtifactStore)


def test_a_local_root_is_resolved_under_home(tmp_path: Path) -> None:
    """Relative state must not depend on the working directory."""
    # Act
    store = _store({"local_root": "artifacts"}, tmp_path)

    # Assert
    assert isinstance(store, LocalArtifactStore)


class _FakeSmb:
    """In-memory stand-in for smbclient, keyed by UNC path."""

    def __init__(self, *, fail_times: int = 0) -> None:
        self.files: dict[str, bytes] = {}
        self.dirs: set[str] = set()
        self.fail_times = fail_times
        self.resets = 0
        self.path = self

    def ClientConfig(self, **kwargs: Any) -> None:  # noqa: N802 - mirrors smbclient's name
        return None

    def reset_connection_cache(self) -> None:
        self.resets += 1

    def makedirs(self, path: str, exist_ok: bool = False) -> None:
        self.dirs.add(path)

    def listdir(self, path: str) -> list[str]:
        if self.fail_times:
            self.fail_times -= 1
            raise ConnectionError("session went stale")
        prefix = path + "\\"
        return [name[len(prefix) :] for name in self.files if name.startswith(prefix)]

    def exists(self, path: str) -> bool:
        return path in self.files

    def remove(self, path: str) -> None:
        if path not in self.files:
            raise FileNotFoundError(path)
        del self.files[path]

    def open_file(self, path: str, mode: str = "rb", encoding: str | None = None) -> Any:
        return _FakeFile(self, path, mode)


class _FakeFile:
    def __init__(self, smb: _FakeSmb, path: str, mode: str) -> None:
        self.smb, self.path, self.mode = smb, path, mode
        self.buffer = bytearray()
        if "r" in mode:
            if path not in smb.files:
                raise FileNotFoundError(path)
            self.data = smb.files[path]

    def __enter__(self) -> Any:
        return self

    def __exit__(self, *exc: object) -> None:
        if "w" in self.mode:
            self.smb.files[self.path] = bytes(self.buffer)

    def read(self, size: int = -1) -> Any:
        data, self.data = (self.data, b"") if size == -1 else (self.data[:size], self.data[size:])
        return data.decode("utf-8") if "b" not in self.mode else data

    def write(self, chunk: Any) -> int:
        self.buffer.extend(chunk.encode("utf-8") if isinstance(chunk, str) else chunk)
        return len(chunk)


@pytest.fixture
def smb(monkeypatch: pytest.MonkeyPatch) -> _FakeSmb:
    fake = _FakeSmb()
    monkeypatch.setitem(__import__("sys").modules, "smbclient", fake)
    return fake


def _configured() -> SmbArtifactStore:
    return SmbArtifactStore(SmbSettings(host="h", share="s", root="fleetctl", user="u", password="p"))


def test_put_then_get_round_trips_over_smb(smb: _FakeSmb, tmp_path: Path) -> None:
    # Arrange
    from fleetctl.core.artifacts.ref import ArtifactRef

    payload = tmp_path / "build.tar.gz"
    payload.write_bytes(b"z" * 256)
    ref = ArtifactRef(kind="builds", name="build.tar.gz")
    store = _configured()

    # Act
    info = store.put(payload, ref, meta={"profile": "gold"})
    restored = store.get(ref, tmp_path / "out.tar.gz")

    # Assert
    assert info.size == 256
    assert info.meta["profile"] == "gold"
    assert restored.read_bytes() == b"z" * 256


def test_listing_excludes_sidecars_and_reads_their_metadata(smb: _FakeSmb, tmp_path: Path) -> None:
    # Arrange
    from fleetctl.core.artifacts.ref import ArtifactRef

    payload = tmp_path / "b.tar.gz"
    payload.write_bytes(b"x")
    store = _configured()
    store.put(payload, ArtifactRef(kind="builds", name="b.tar.gz"), meta={"kodi_version": "21.3"})

    # Act
    found = store.list("builds")

    # Assert
    assert [info.ref.name for info in found] == ["b.tar.gz"]
    assert found[0].meta["kodi_version"] == "21.3"


def test_exists_and_delete_behave(smb: _FakeSmb, tmp_path: Path) -> None:
    # Arrange
    from fleetctl.core.artifacts.ref import ArtifactRef

    payload = tmp_path / "b.tar.gz"
    payload.write_bytes(b"x")
    ref = ArtifactRef(kind="builds", name="b.tar.gz")
    store = _configured()
    store.put(payload, ref)

    # Act
    present = store.exists(ref)
    store.delete(ref)
    store.delete(ref)  # absent is not an error

    # Assert
    assert present is True
    assert store.exists(ref) is False


def test_latest_picks_the_newest(smb: _FakeSmb, tmp_path: Path) -> None:
    # Arrange
    from fleetctl.core.artifacts.ref import ArtifactRef

    store = _configured()
    for index, name in enumerate(("build_1.tar.gz", "build_2.tar.gz")):
        payload = tmp_path / name
        payload.write_bytes(b"x")
        store.put(payload, ArtifactRef(kind="builds", name=name), meta={"created_at": f"2026-08-0{index + 1}T00:00:00"})

    # Act / Assert
    assert store.latest("builds").name == "build_2.tar.gz"


def test_missing_artifact_reports_clearly(smb: _FakeSmb, tmp_path: Path) -> None:
    # Arrange
    from fleetctl.core.artifacts.ref import ArtifactRef

    # Act / Assert
    with pytest.raises(ArtifactError):
        _configured().get(ArtifactRef(kind="builds", name="nope.tar.gz"), tmp_path / "x")


def test_a_stale_session_is_retried_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """SMB sessions go stale between runs far more often than they fail."""
    # Arrange
    fake = _FakeSmb(fail_times=1)
    monkeypatch.setitem(__import__("sys").modules, "smbclient", fake)

    # Act
    _configured().list("builds")

    # Assert
    assert fake.resets == 1


def test_listing_an_absent_kind_is_empty_not_an_error(smb: _FakeSmb) -> None:
    assert _configured().list("captures") == []


def test_a_secret_username_reaches_the_server_unmasked(smb: _FakeSmb) -> None:
    """`str()` on a Secret yields its mask. Coercing the username that way
    authenticated as the literal mask, and the server silently downgraded the
    session to guest -- every listing came back empty against a full share."""
    # Arrange
    settings = SmbSettings.from_mapping(
        {"host": "h", "share": "s", "root": "r", "user": Secret("real-user", origin="env:SMB_USER"), "password": Secret("pw", origin="env:SMB_PASS")}
    )

    # Act
    SmbArtifactStore(settings)._connect()

    # Assert
    assert settings.reveal_user() == "real-user"
    assert "real-user" not in str(settings.user)
    assert settings.configured is True


def test_a_secret_username_that_resolves_to_nothing_is_not_configured(smb: _FakeSmb) -> None:
    """A masked non-empty string would otherwise look like a valid username."""
    # Act
    settings = SmbSettings.from_mapping({"host": "h", "share": "s", "user": Secret("", origin="env:SMB_USER")})

    # Assert
    assert settings.configured is False
