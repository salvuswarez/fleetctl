"""The capture -> build -> deploy pipeline, end to end without hardware.

The load-bearing assertion in this file is `test_the_app_pack_issues_no_tar_
command`: the Fire OS archive quirk appears in the commands sent to the
device, but `apps/kodi` never wrote one. That is decision 3 working.
"""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from fleetctl.apps.kodi import steps
from fleetctl.apps.kodi.spec import PROFILE_MEMBERS, state_spec
from fleetctl.apps.kodi.transforms.addons import PruneAddons
from fleetctl.apps.kodi.transforms.settings import ApplySettings
from fleetctl.core.artifacts.ref import ArtifactRef
from fleetctl.core.artifacts.store import LocalArtifactStore
from fleetctl.core.errors import ArtifactError, FleetError
from fleetctl.core.inventory.device import Device
from fleetctl.core.inventory.store import DeviceStore
from fleetctl.core.observability.audit import ChainedAuditWriter, InMemoryAuditSink
from fleetctl.core.operations.registry import OperationRegistry
from fleetctl.core.state import StateManager
from fleetctl.core.transport.auditing import AuditingTransport
from fleetctl.core.transport.fake import FakeTransport
from fleetctl.core.workflow.step import DeviceStepContext, TransformStepContext
from fleetctl.packs.android.appmgr import AndroidAppManager
from fleetctl.packs.android.quirks import AndroidQuirks
from fleetctl.packs.android.state import AndroidStateManager

FIRE_OS = AndroidQuirks(split_gzip=True, push_via_netcat=True, verify_disable_user=True)
ROOT = "/sdcard/Android/data/org.xbmc.kodi/files/.kodi"


def _make_profile(root: Path) -> Path:
    """Build a small but realistic profile tree."""
    for addon in ("skin.example", "plugin.video.example", "script.module.dep", "plugin.video.unwanted"):
        (root / "addons" / addon).mkdir(parents=True)
        (root / "addons" / addon / "addon.xml").write_text("<addon/>", encoding="utf-8")
    (root / "userdata" / "addon_data" / "skin.example").mkdir(parents=True)
    (root / "userdata" / "addon_data" / "skin.example" / "settings.xml").write_text(
        '<settings version="2"><setting id="startup.preload">true</setting></settings>', encoding="utf-8"
    )
    (root / "userdata" / "Thumbnails").mkdir(parents=True)
    (root / "media").mkdir(parents=True)
    return root


@pytest.fixture
def store(tmp_path: Path) -> LocalArtifactStore:
    return LocalArtifactStore(tmp_path / "store")


@pytest.fixture
def capture_artifact(tmp_path: Path, store: LocalArtifactStore) -> ArtifactRef:
    """A published capture, wrapped in `.kodi/` the way a device produces it."""
    staging = tmp_path / "src"
    _make_profile(staging / ".kodi")
    archive = tmp_path / "capture.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(staging / ".kodi", arcname=".kodi")
    ref = ArtifactRef(kind=steps.CAPTURES, name="capture.tar.gz")
    store.put(archive, ref)
    return ref


def _transform_context(tmp_path: Path, store: LocalArtifactStore, config: dict[str, object]) -> TransformStepContext:
    registry = OperationRegistry()
    workspace = tmp_path / "ws-build"
    workspace.mkdir(exist_ok=True)
    return TransformStepContext(
        transforms=(
            PruneAddons(allow=["skin.example", "plugin.video.example"], allow_prefixes=("script.module.",)),
            ApplySettings(overrides={"addon_data/skin.example/settings.xml": {"startup.preload": "false"}}),
        ),
        artifacts=store,
        config=config,
        handle=registry.start("op-build", steps.BUILD.id),
        workspace=workspace,
    )


def _device_context(
    tmp_path: Path, store: LocalArtifactStore, transport: AuditingTransport, config: dict[str, object], name: str, state: StateManager | None = None
) -> DeviceStepContext:
    device = Device(id="stick-1", type="firetv", address="192.168.1.50", name="Living Room")
    inventory = DeviceStore(tmp_path / "devices.yml")
    inventory.save([device])
    registry = OperationRegistry()
    workspace = tmp_path / name
    workspace.mkdir(exist_ok=True)
    return DeviceStepContext(
        device=device,
        transport=transport,
        state=state if state is not None else AndroidStateManager(transport, FIRE_OS),
        apps=AndroidAppManager(transport, FIRE_OS),
        artifacts=store,
        inventory=inventory,
        config=config,
        handle=registry.start(f"op-{name}", steps.DEPLOY.id, device.id),
        workspace=workspace,
    )


def test_build_applies_every_transform_and_publishes_a_flat_archive(tmp_path: Path, store: LocalArtifactStore, capture_artifact: ArtifactRef) -> None:
    # Arrange
    context = _transform_context(tmp_path, store, {"source": capture_artifact.wire})

    # Act
    result = steps.build(context)

    # Assert
    ref = result.artifacts["build"]
    local = store.get(ref, tmp_path / "out.tar.gz")
    with tarfile.open(local, "r:gz") as archive:
        names = archive.getnames()
    assert "addons" in names
    assert not [name for name in names if name.startswith(".kodi")]
    assert not [name for name in names if "plugin.video.unwanted" in name]
    assert "addons/script.module.dep" in names


def test_build_defaults_to_the_latest_capture(tmp_path: Path, store: LocalArtifactStore, capture_artifact: ArtifactRef) -> None:
    # Arrange
    context = _transform_context(tmp_path, store, {})

    # Act
    result = steps.build(context)

    # Assert
    assert result.facts["source"] == capture_artifact.wire


def test_build_fails_clearly_when_there_is_nothing_to_build_from(tmp_path: Path, store: LocalArtifactStore) -> None:
    # Arrange
    context = _transform_context(tmp_path, store, {})

    # Act / Assert
    with pytest.raises(ArtifactError):
        steps.build(context)


def test_a_build_can_be_rebuilt_from_its_own_flat_output(tmp_path: Path, store: LocalArtifactStore, capture_artifact: ArtifactRef) -> None:
    """A capture is wrapped; a build is flat. Accepting both avoids a special
    case that would otherwise bite on a rebuild."""
    # Arrange
    first = steps.build(_transform_context(tmp_path, store, {"source": capture_artifact.wire}))

    # Act
    second = steps.build(_transform_context(tmp_path, store, {"source": first.artifacts["build"].wire}))

    # Assert
    assert second.artifacts["build"].kind == steps.BUILDS


def test_deploy_hands_the_build_to_the_device_pack(tmp_path: Path, store: LocalArtifactStore, capture_artifact: ArtifactRef) -> None:
    # Arrange
    built = steps.build(_transform_context(tmp_path, store, {"source": capture_artifact.wire}))
    inner = FakeTransport(
        responses={
            f"mkdir -p {ROOT}": "",
            f"ls {ROOT}/addons": "skin.example",
            f"ls {ROOT}/userdata": "addon_data",
            f"ls {ROOT}/media": "art",
        }
    )
    inner.responses = {**inner.responses, **{f"gzip -d /sdcard/{built.artifacts['build'].name}": ""}}
    inner.responses = {**inner.responses, **{f"tar xf /sdcard/{built.artifacts['build'].name.removesuffix('.gz')} -C {ROOT}": ""}}
    transport = AuditingTransport(inner, ChainedAuditWriter(InMemoryAuditSink()))
    context = _device_context(tmp_path, store, transport, {"build": built.artifacts["build"].wire}, "ws-deploy")

    # Act
    result = steps.deploy(context)

    # Assert
    assert built.artifacts["build"].wire in result.summary
    assert f"rm -rf {ROOT}/addons" in inner.commands()


def test_deploy_refuses_a_raw_capture(tmp_path: Path, store: LocalArtifactStore, capture_artifact: ArtifactRef) -> None:
    """Deploy ships built profiles. A raw capture has had no transform run."""
    # Arrange
    transport = AuditingTransport(FakeTransport(), ChainedAuditWriter(InMemoryAuditSink()))
    context = _device_context(tmp_path, store, transport, {"build": capture_artifact.wire}, "ws-bad")

    # Act / Assert
    with pytest.raises(ArtifactError):
        steps.deploy(context)


def test_the_app_pack_issues_no_tar_command(tmp_path: Path, store: LocalArtifactStore, capture_artifact: ArtifactRef) -> None:
    """Decision 3, asserted.

    The Fire OS split-gzip quirk shows up in what the device is sent, but
    `apps/kodi` never wrote a `tar` or a path — the device pack did, from its
    own quirk data. A Shield swapping in different quirks changes these
    commands without touching this app pack.
    """
    # Arrange
    built = steps.build(_transform_context(tmp_path, store, {"source": capture_artifact.wire}))
    name = built.artifacts["build"].name
    inner = FakeTransport(
        responses={
            f"gzip -d /sdcard/{name}": "",
            f"tar xf /sdcard/{name.removesuffix('.gz')} -C {ROOT}": "",
            f"mkdir -p {ROOT}": "",
            f"ls {ROOT}/addons": "skin.example",
            f"ls {ROOT}/userdata": "addon_data",
            f"ls {ROOT}/media": "art",
        }
    )
    transport = AuditingTransport(inner, ChainedAuditWriter(InMemoryAuditSink()))
    context = _device_context(tmp_path, store, transport, {"build": built.artifacts["build"].wire}, "ws-seam")

    # Act
    steps.deploy(context)

    # Assert
    issued = inner.commands()
    assert any(command.startswith("gzip -d") for command in issued)
    assert any(command.startswith("tar xf") for command in issued)

    source = Path(steps.__file__).read_text(encoding="utf-8")
    assert "tar " not in source
    assert "/sdcard" not in source


def test_the_kodi_package_names_no_device_path() -> None:
    """A grep-level guard on the whole app pack, not just the steps module."""
    # Arrange
    package = Path(steps.__file__).parent

    # Act
    offenders = [
        f"{path.name}: {line.strip()}"
        for path in package.rglob("*.py")
        for line in path.read_text(encoding="utf-8").splitlines()
        if "/sdcard" in line.split("#", 1)[0]
    ]

    # Assert
    assert offenders == []


def test_capture_publishes_a_verified_artifact(tmp_path: Path, store: LocalArtifactStore) -> None:
    # Arrange
    staged = _make_profile(tmp_path / "live" / ".kodi")
    archive = tmp_path / "snap.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(staged, arcname=".kodi")

    class _Manager:
        platform = "android"

        def state_root(self, spec: object) -> str:
            return ROOT

        def snapshot(self, spec: object, destination: Path) -> Path:
            destination.write_bytes(archive.read_bytes())
            return destination

        def restore(self, spec: object, archive_path: Path) -> None:
            raise AssertionError("capture must not restore")

    transport = AuditingTransport(FakeTransport(), ChainedAuditWriter(InMemoryAuditSink()))
    context = _device_context(tmp_path, store, transport, {}, "ws-capture", state=_Manager())

    # Act
    result = steps.capture(context)

    # Assert
    ref = result.artifacts["capture"]
    assert ref.kind == steps.CAPTURES
    assert store.exists(ref)


def test_a_truncated_capture_is_rejected_rather_than_published(tmp_path: Path, store: LocalArtifactStore) -> None:
    """The predecessor published bad archives as if good; they surfaced much
    later on an unrelated device's deploy."""

    # Arrange
    class _Manager:
        platform = "android"

        def state_root(self, spec: object) -> str:
            return ROOT

        def snapshot(self, spec: object, destination: Path) -> Path:
            destination.write_bytes(b"\x1f\x8b\x08\x00 truncated nonsense")
            return destination

        def restore(self, spec: object, archive_path: Path) -> None:
            raise AssertionError("capture must not restore")

    transport = AuditingTransport(FakeTransport(), ChainedAuditWriter(InMemoryAuditSink()))
    context = _device_context(tmp_path, store, transport, {}, "ws-bad-capture", state=_Manager())

    # Act / Assert
    with pytest.raises(FleetError):
        steps.capture(context)
    assert store.list(steps.CAPTURES) == []


def test_the_state_spec_declares_kodis_members_and_exclusions() -> None:
    # Act
    spec = state_spec()

    # Assert
    assert spec.identifiers["android"] == "org.xbmc.kodi"
    assert spec.members == PROFILE_MEMBERS
    assert "userdata/Thumbnails" in spec.exclude
    assert "userdata/Database/Textures13.db" in spec.exclude


def test_deploy_refuses_a_build_shaped_for_other_hardware(tmp_path: Path, store: LocalArtifactStore, capture_artifact: ArtifactRef) -> None:
    """`kodi-refresh` deploys the newest build to everything tagged `kodi`. A
    gold build carries ARM addon binaries, so reaching an x86 Steam Deck that
    way installs cleanly and then crashes on playback -- the failure this
    guard exists to make loud and early."""
    # Arrange
    built = steps.build(_transform_context(tmp_path, store, {"source": capture_artifact.wire, "profile": "gold"}))
    inner = FakeTransport()
    transport = AuditingTransport(inner, ChainedAuditWriter(InMemoryAuditSink()))
    config: dict[str, object] = {"build": built.artifacts["build"].wire, "profile": "deck"}
    context = _device_context(tmp_path, store, transport, config, "ws-mismatch")

    # Act / Assert
    with pytest.raises(FleetError, match="built with the 'gold' profile"):
        steps.deploy(context)
    # Refused before the profile was wiped, not part-way through restoring it.
    assert not inner.commands()


def test_deploy_allows_a_build_with_no_recorded_profile(tmp_path: Path, store: LocalArtifactStore, capture_artifact: ArtifactRef) -> None:
    """Builds published before profiles were recorded must stay deployable;
    only a definite disagreement stops."""
    # Arrange
    built = steps.build(_transform_context(tmp_path, store, {"source": capture_artifact.wire}))
    name = built.artifacts["build"].name
    inner = FakeTransport(
        responses={
            f"mkdir -p {ROOT}": "",
            f"ls {ROOT}/addons": "skin.example",
            f"ls {ROOT}/userdata": "addon_data",
            f"ls {ROOT}/media": "art",
            f"gzip -d /sdcard/{name}": "",
            f"tar xf /sdcard/{name.removesuffix('.gz')} -C {ROOT}": "",
        }
    )
    transport = AuditingTransport(inner, ChainedAuditWriter(InMemoryAuditSink()))
    context = _device_context(tmp_path, store, transport, {"build": built.artifacts["build"].wire, "profile": "deck"}, "ws-legacy")

    # Act
    result = steps.deploy(context)

    # Assert
    assert built.artifacts["build"].wire in result.summary
