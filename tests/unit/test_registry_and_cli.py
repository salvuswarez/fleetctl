"""Tests for pack discovery and the CLI that is generated from it."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import pytest
from click.testing import CliRunner

from fleetctl.apps.kodi.pack import KodiApp
from fleetctl.cli.bootstrap import build_container
from fleetctl.cli.main import main
from fleetctl.core.effects import Capability, Effect
from fleetctl.core.errors import FleetError
from fleetctl.core.registry import RegisteredStep, Registry, discover
from fleetctl.core.transport.base import CommandRunner
from fleetctl.core.workflow.step import StepResult, StepSpec
from fleetctl.packs.firetv.pack import FireTvPack


class _StubPack:
    """A minimal device pack, for registration tests."""

    def __init__(self, pack_id: str = "stub", step_id: str = "stub.noop", priority: int = 50) -> None:
        self.id = pack_id
        self.platform = "stub"
        self.capabilities = frozenset({Capability.EXEC})
        self.probe_priority = priority
        self.app_profiles: dict[str, str] = {}
        self._step_id = step_id

    def probe(self, runner: CommandRunner) -> dict[str, str] | None:
        return None

    def steps(self) -> Iterable[RegisteredStep]:
        spec = StepSpec(id=self._step_id, summary="noop", effect=Effect.READ)
        return [RegisteredStep(spec=spec, run=lambda context: StepResult(summary="ok"), provider=self.id)]


def test_a_registered_pack_exposes_its_steps() -> None:
    # Arrange
    registry = Registry()

    # Act
    registry.register_device_pack(_StubPack())

    # Assert
    assert registry.device_pack("stub").id == "stub"
    assert registry.step("stub.noop").provider == "stub"


def test_registering_the_same_pack_twice_is_rejected() -> None:
    # Arrange
    registry = Registry()
    registry.register_device_pack(_StubPack())

    # Act / Assert
    with pytest.raises(FleetError):
        registry.register_device_pack(_StubPack())


def test_two_packs_cannot_claim_the_same_step_id() -> None:
    """A silent overwrite would let one pack shadow another's steps."""
    # Arrange
    registry = Registry()
    registry.register_device_pack(_StubPack(pack_id="one", step_id="shared.step"))

    # Act / Assert
    with pytest.raises(FleetError) as caught:
        registry.register_device_pack(_StubPack(pack_id="two", step_id="shared.step"))
    assert "one" in str(caught.value)


def test_an_unknown_pack_names_what_is_available() -> None:
    # Arrange
    registry = Registry()
    registry.register_device_pack(_StubPack())

    # Act / Assert
    with pytest.raises(FleetError) as caught:
        registry.device_pack("nope")
    assert "stub" in str(caught.value)


def test_packs_are_ordered_for_probing() -> None:
    """Probe order decides which pack claims a host, so it must be explicit."""
    # Arrange
    registry = Registry()
    registry.register_device_pack(_StubPack(pack_id="late", step_id="late.noop", priority=99))
    registry.register_device_pack(_StubPack(pack_id="early", step_id="early.noop", priority=1))

    # Act
    ordered = [pack.id for pack in registry.device_packs()]

    # Assert
    assert ordered == ["early", "late"]


def test_a_broken_pack_is_skipped_rather_than_breaking_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    """One third-party pack failing to import must not stop you managing the
    devices you can still reach."""

    # Arrange
    class _Entry:
        name = "broken"

        def load(self) -> Any:
            raise ImportError("its optional dependency is missing")

    monkeypatch.setattr("fleetctl.core.registry.metadata.entry_points", lambda group: [_Entry()] if group == "fleetctl.packs" else [])

    # Act
    registry = discover(Registry())

    # Assert
    assert registry.device_packs() == []


def test_the_shipped_packs_are_discovered_through_entry_points() -> None:
    """The registration path a third-party pack would use, exercised on our
    own packs rather than bypassed in tests."""
    # Act
    registry = discover()

    # Assert
    assert registry.device_pack("firetv").id == "firetv"
    assert registry.app_pack("kodi").id == "kodi"
    assert {step.spec.id for step in registry.steps()} >= {"firetv.maintain", "kodi.capture", "kodi.build", "kodi.deploy"}


def test_the_kodi_app_builds_its_transform_chain_from_the_shipped_recipe() -> None:
    """Order matters: addons are pruned first, so settings are not applied to
    files that are about to be deleted, and device settings are stripped before
    the recipe's own overrides so a deliberately pinned key wins."""
    # Act
    transforms = KodiApp().transforms

    # Assert
    assert [transform.name for transform in transforms] == [
        "prune_addons",
        "strip_device_settings",
        "apply_settings",
        "remove_thumbnail_substitution",
        "apply_view_types",
        "apply_hub_layout",
    ]


def test_a_recipe_with_nothing_configured_yields_only_the_always_on_transforms() -> None:
    """A transform whose config is absent is not added, so a minimal profile
    does not pay for skin-specific work it does not need. Stripping device
    settings is not one of those: a shared artifact must never carry one
    device's calibration, so no recipe can opt out by omission."""
    # Act
    transforms = KodiApp(overrides={}).transforms

    # Assert
    assert [transform.name for transform in transforms] == ["prune_addons", "strip_device_settings", "apply_settings"]


def test_the_firetv_pack_registers_its_steps_under_its_own_id() -> None:
    """Every step a pack registers is namespaced to it, including the ones
    whose implementation is shared with the other Android pack."""
    # Act
    steps = list(FireTvPack().steps())

    # Assert
    assert [step.spec.id for step in steps] == [
        "firetv.maintain",
        "firetv.check",
        "firetv.capture_state",
        "firetv.restore_state",
    ]
    assert all(step.provider == "firetv" for step in steps)


def test_each_firetv_step_declares_the_effect_its_gating_depends_on() -> None:
    """A mislabelled destructive step bypasses approval silently, so the
    classes are asserted individually rather than by position."""
    # Act
    effects = {step.spec.id: step.spec.effect for step in FireTvPack().steps()}

    # Assert
    assert effects["firetv.maintain"] is Effect.DESTRUCTIVE
    assert effects["firetv.check"] is Effect.READ
    # Reads settings, reads the package list, pulls files. Changes nothing.
    assert effects["firetv.capture_state"] is Effect.READ
    # Rewrites system settings and reinstalls packages over what is there.
    assert effects["firetv.restore_state"] is Effect.DESTRUCTIVE


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "config" / "inventory").mkdir(parents=True)
    (tmp_path / "config" / "fleet.yml").write_text("observability:\n  audit_dir: audit\n", encoding="utf-8")
    (tmp_path / "config" / "inventory" / "devices.yml").write_text(
        "devices:\n  - id: stick-1\n    type: firetv\n    address: 192.168.1.50\n    tags: [kodi]\n", encoding="utf-8"
    )
    return tmp_path


def _invoke(workspace: Path, *args: str) -> Any:
    return CliRunner().invoke(main, ["--config-dir", str(workspace / "config"), "--home", str(workspace / "home"), *args])


def test_steps_command_lists_every_registered_step(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "steps")

    # Assert
    assert result.exit_code == 0
    assert "kodi.deploy" in result.output
    assert "firetv.maintain" in result.output


def test_steps_command_shows_the_effect_class(workspace: Path) -> None:
    """An operator should be able to see what is destructive before running it."""
    # Act
    result = _invoke(workspace, "steps")

    # Assert
    assert "destructive" in result.output


def test_packs_command_lists_installed_packs(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "packs")

    # Assert
    assert result.exit_code == 0
    assert "firetv" in result.output


def test_devices_list_reads_the_inventory(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "devices", "list")

    # Assert
    assert result.exit_code == 0
    assert "stick-1" in result.output
    assert "192.168.1.50" in result.output


def test_devices_list_is_empty_without_an_inventory(tmp_path: Path) -> None:
    # Act
    result = _invoke(tmp_path, "devices", "list")

    # Assert
    assert result.exit_code == 0
    assert "No devices" in result.output


def test_running_an_unknown_step_names_what_exists(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "run", "nope.nothing")

    # Assert
    assert result.exit_code != 0
    assert "kodi.capture" in result.output


def test_a_device_step_without_a_device_is_a_usage_error(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "run", "kodi.deploy")

    # Assert
    assert result.exit_code != 0
    assert "--device" in result.output


def test_running_against_an_unknown_device_fails_clearly(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "run", "kodi.deploy", "--device", "ghost")

    # Assert
    assert result.exit_code != 0
    assert "Unknown device: ghost" in result.output


def test_config_show_explains_where_each_value_came_from(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "config", "stick-1")

    # Assert
    assert result.exit_code == 0
    assert "[fleet]" in result.output


def test_set_requires_key_equals_value(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "run", "kodi.build", "--set", "malformed")

    # Assert
    assert result.exit_code != 0
    assert "KEY=VALUE" in result.output


def test_audit_verify_reports_an_empty_trail(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "audit", "verify")

    # Assert
    assert result.exit_code == 0
    assert "No audit records" in result.output


def test_the_container_resolves_secret_references(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fleet.yml holds pointers; values arrive from the environment."""
    # Arrange
    monkeypatch.setenv("FLEETCTL_TEST_TOKEN", "hunter2")
    (workspace / "config" / "fleet.yml").write_text("artifacts:\n  token: !ref env:FLEETCTL_TEST_TOKEN\n", encoding="utf-8")

    # Act
    container = build_container(config_dir=workspace / "config", home=workspace / "home")

    # Assert
    assert container.config["artifacts"]["token"].reveal() == "hunter2"


def test_a_build_step_runs_without_any_device(workspace: Path) -> None:
    """A fleet-scoped step must not need a transport. It fails here only
    because there is nothing captured yet, not because of a device."""
    # Act
    result = _invoke(workspace, "run", "kodi.build")

    # Assert
    assert result.exit_code != 0
    assert "captures" in result.output.lower()


def test_workflow_list_includes_the_shipped_workflow(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "workflow", "list")

    # Assert
    assert result.exit_code == 0
    assert "kodi-refresh" in result.output


def test_workflow_plan_shows_targets_and_a_digest(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "workflow", "plan", "kodi-refresh")

    # Assert
    assert result.exit_code == 0
    assert "stick-1" in result.output
    assert "digest:" in result.output


def test_a_dry_run_executes_nothing(workspace: Path) -> None:
    """The S3 exit criterion: a plan you can read before anything happens."""
    # Act
    result = _invoke(workspace, "workflow", "run", "kodi-refresh", "--dry-run")

    # Assert
    assert result.exit_code == 0
    assert "nothing was executed" in result.output
    assert (workspace / "home" / "audit").exists() is False


def test_an_unknown_workflow_names_what_exists(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "workflow", "plan", "nope")

    # Assert
    assert result.exit_code != 0
    assert "kodi-refresh" in result.output


def test_a_stale_plan_digest_is_refused(workspace: Path) -> None:
    """So a run cannot execute against a fleet that changed after planning."""
    # Act
    result = _invoke(workspace, "workflow", "run", "kodi-refresh", "--confirm", "0" * 64)

    # Assert
    assert result.exit_code != 0
    assert "changed since" in result.output


def test_a_user_workflow_shadows_a_shipped_one(workspace: Path) -> None:
    """Shipping a workflow is a starting point, not a constraint."""
    # Arrange
    (workspace / "config" / "workflows").mkdir()
    (workspace / "config" / "workflows" / "kodi-refresh.yml").write_text(
        "name: kodi-refresh\ndescription: mine\nsteps:\n  - use: kodi.build\n    targets: none\n", encoding="utf-8"
    )

    # Act
    result = _invoke(workspace, "workflow", "plan", "kodi-refresh")

    # Assert
    assert result.exit_code == 0
    assert "maintain" not in result.output


def _with_policy(workspace: Path, policy_yaml: str) -> None:
    (workspace / "config" / "fleet.yml").write_text(f"observability:\n  audit_dir: audit\npolicy:\n{policy_yaml}", encoding="utf-8")


def test_a_protected_device_is_refused_and_the_denial_is_audited(workspace: Path) -> None:
    # Arrange
    _with_policy(
        workspace,
        "  protected:\n    - match: {tags: [kodi]}\n      deny: ['kodi.deploy']\n      reason: held back for now\n  actors:\n    'cli:*': {allow: ['*']}\n",
    )

    # Act
    result = _invoke(workspace, "run", "kodi.deploy", "--device", "stick-1")
    tailed = _invoke(workspace, "audit", "tail")

    # Assert
    assert result.exit_code != 0
    assert "held back for now" in result.output
    assert "policy.deny" in tailed.output


def test_an_unknown_actor_is_denied_when_a_policy_exists(workspace: Path) -> None:
    # Arrange
    _with_policy(workspace, "  actors:\n    'mcp:*': {allow: ['*']}\n")

    # Act
    result = _invoke(workspace, "run", "kodi.build")

    # Assert
    assert result.exit_code != 0
    assert "No policy rule covers actor" in result.output


def test_a_workflow_needing_approval_refuses_without_the_flag(workspace: Path) -> None:
    # Arrange
    _with_policy(workspace, "  actors:\n    'cli:*': {allow: ['*'], confirm: ['destructive']}\n")

    # Act
    result = _invoke(workspace, "workflow", "run", "kodi-refresh")

    # Assert
    assert result.exit_code != 0
    assert "Approval required" in result.output


def test_the_plan_shows_what_needs_approval(workspace: Path) -> None:
    # Arrange
    _with_policy(workspace, "  actors:\n    'cli:*': {allow: ['*'], confirm: ['destructive']}\n")

    # Act
    result = _invoke(workspace, "workflow", "plan", "kodi-refresh")

    # Assert
    assert "NEEDS APPROVAL" in result.output


def test_a_blast_radius_cap_refuses_an_oversized_run(workspace: Path) -> None:
    # Arrange
    (workspace / "config" / "inventory" / "devices.yml").write_text(
        "devices:\n" + "".join(f"  - id: stick-{n}\n    type: firetv\n    address: 192.168.1.5{n}\n    tags: [kodi]\n" for n in range(4)),
        encoding="utf-8",
    )
    _with_policy(workspace, "  actors:\n    'cli:*': {allow: ['*'], max_devices: 2}\n")

    # Act
    result = _invoke(workspace, "workflow", "run", "kodi-refresh")

    # Assert
    assert result.exit_code != 0
    assert "at most 2" in result.output


def test_a_denial_records_who_was_refused(workspace: Path) -> None:
    """A record that cannot say who was refused is half a record."""
    # Arrange
    _with_policy(workspace, "  actors:\n    'cli:*': {allow: ['*'], deny: ['kodi.deploy']}\n")

    # Act
    _invoke(workspace, "run", "kodi.deploy", "--device", "stick-1")
    from fleetctl.core.observability.audit import JsonlAuditSink

    events = JsonlAuditSink(workspace / "home" / "audit").read_all()

    # Assert
    assert events
    assert events[-1].actor.startswith("cli:")
    assert events[-1].target == "stick-1"


def _fake_scan(monkeypatch: pytest.MonkeyPatch, hosts: list[Any], claims: list[Any]) -> None:
    """Replace the network parts of `scan`, leaving its wiring under test."""
    monkeypatch.setattr("fleetctl.core.discovery.scan.Sweeper", lambda *a, **k: type("S", (), {"sweep": lambda self, subnet: hosts})())
    monkeypatch.setattr("fleetctl.core.discovery.scan.claim_hosts", lambda hosts, packs, connect: claims)


def test_scan_writes_discovered_devices_to_the_inventory(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    from fleetctl.core.discovery.claim import Claim
    from fleetctl.core.discovery.sweep import Host
    from fleetctl.core.inventory.device import Device

    host = Host(address="192.168.1.60", mac="aa:bb:cc:00:11:22")
    found = Device(id="den-shield", type="shield", address="192.168.1.60", mac="aa:bb:cc:00:11:22", model="SHIELD")
    _fake_scan(monkeypatch, [host], [Claim(host=host, device=found, pack_id="shield")])

    # Act
    result = _invoke(workspace, "scan", "192.168.1.0/24")

    # Assert
    assert result.exit_code == 0, result.output
    assert "den-shield" in result.output
    listed = _invoke(workspace, "devices", "list")
    assert "den-shield" in listed.output


def test_scan_summarises_unrecognized_hosts_rather_than_listing_them(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real /24 is mostly hosts no pack knows. Listing them all buried the
    few that mattered under 250 lines."""
    # Arrange
    from fleetctl.core.discovery.claim import Claim
    from fleetctl.core.discovery.sweep import Host

    _fake_scan(monkeypatch, [Host(address="192.168.1.90")], [Claim(host=Host(address="192.168.1.90"))])

    # Act
    result = _invoke(workspace, "scan", "192.168.1.0/24")

    # Assert
    assert result.exit_code == 0
    assert "1 host(s) not recognized" in result.output
    assert "192.168.1.90" not in result.output


def test_a_scan_dry_run_writes_nothing(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    from fleetctl.core.discovery.claim import Claim
    from fleetctl.core.discovery.sweep import Host
    from fleetctl.core.inventory.device import Device

    host = Host(address="192.168.1.60")
    _fake_scan(monkeypatch, [host], [Claim(host=host, device=Device(id="new-one", type="shield"), pack_id="shield")])

    # Act
    result = _invoke(workspace, "scan", "192.168.1.0/24", "--dry-run")

    # Assert
    assert "inventory not written" in result.output
    assert "new-one" not in _invoke(workspace, "devices", "list").output


def test_a_rescan_updates_a_moved_device_without_losing_hand_edits(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole point of an editable inventory: tags and per-app vars are
    yours, and a scan refreshes only what it actually observed."""
    # Arrange
    (workspace / "config" / "inventory" / "devices.yml").write_text(
        "devices:\n"
        "  - id: stick-1\n"
        "    type: firetv\n"
        "    address: 192.168.1.50\n"
        "    mac: aa:bb:cc:dd:ee:ff\n"
        "    name: Living Room\n"
        "    tags: [kodi, lounge]\n"
        "    vars:\n"
        "      kodi:\n"
        "        display: {resolution_index: 18}\n",
        encoding="utf-8",
    )
    from fleetctl.core.discovery.claim import Claim
    from fleetctl.core.discovery.sweep import Host
    from fleetctl.core.inventory.device import Device

    moved = Host(address="192.168.1.77", mac="aa:bb:cc:dd:ee:ff")
    _fake_scan(
        monkeypatch,
        [moved],
        [Claim(host=moved, device=Device(id="rediscovered", type="firetv", address="192.168.1.77", mac="aa:bb:cc:dd:ee:ff"), pack_id="firetv")],
    )

    # Act
    result = _invoke(workspace, "scan", "192.168.1.0/24")

    # Assert
    assert "Added 0, updated 1" in result.output
    from fleetctl.core.inventory.store import DeviceStore

    device = DeviceStore(workspace / "config" / "inventory" / "devices.yml").get("stick-1")
    assert device is not None
    assert device.address == "192.168.1.77"
    assert device.tags == ["kodi", "lounge"]
    assert device.app_vars("kodi")["display"] == {"resolution_index": 18}
    assert device.name == "Living Room"


def test_scan_refuses_a_subnet_too_large_to_sweep(workspace: Path) -> None:
    # Act
    result = _invoke(workspace, "scan", "10.0.0.0/8")

    # Assert
    assert result.exit_code != 0
    assert "Refusing to sweep" in result.output


def test_scan_tells_you_where_the_inventory_lives(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """It is a plain YAML file the user owns; say so."""
    # Arrange
    from fleetctl.core.discovery.claim import Claim
    from fleetctl.core.discovery.sweep import Host
    from fleetctl.core.inventory.device import Device

    host = Host(address="192.168.1.60")
    _fake_scan(monkeypatch, [host], [Claim(host=host, device=Device(id="x", type="shield"), pack_id="shield")])

    # Act
    result = _invoke(workspace, "scan", "192.168.1.0/24")

    # Assert
    assert "devices.yml" in result.output
    assert "Edit that file directly" in result.output


def test_scan_tells_you_which_hosts_refused_the_key(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ "Nothing there" and "it said no" need different actions from the user."""
    # Arrange
    from fleetctl.core.discovery.claim import Claim
    from fleetctl.core.discovery.sweep import Host

    refused = Host(address="192.168.1.79")
    stranger = Host(address="192.168.1.91")
    _fake_scan(monkeypatch, [refused, stranger], [Claim(host=refused, unauthorized=True), Claim(host=stranger)])

    # Act
    result = _invoke(workspace, "scan", "192.168.1.0/24")

    # Assert
    assert "192.168.1.79" in result.output
    assert "refused this key" in result.output
    assert "Approve the debugging prompt" in result.output
    assert "1 host(s) not recognized" in result.output


def test_dotted_overrides_nest_so_they_merge_with_device_vars() -> None:
    """`--set kodi.display.resolution_index=18` is how apply-display survives
    without a command of its own; a flat key would sit beside `kodi`, not in it."""
    # Act
    from fleetctl.cli.main import _parse_overrides

    parsed = _parse_overrides(("kodi.display.resolution_index=18", "kodi.display.overscan.right=1920"))

    # Assert
    assert parsed == {"kodi": {"display": {"resolution_index": 18, "overscan": {"right": 1920}}}}


def test_override_values_arrive_typed() -> None:
    """A step comparing `dry_run` to True would never match the string "true"."""
    # Act
    from fleetctl.cli.main import _parse_overrides

    parsed = _parse_overrides(("dry_run=true", "count=3", "name=gold", "subnet=192.168.1.0/24"))

    # Assert
    assert parsed == {"dry_run": True, "count": 3, "name": "gold", "subnet": "192.168.1.0/24"}


def test_an_override_that_is_not_a_pair_is_rejected() -> None:
    # Act / Assert
    import click

    from fleetctl.cli.main import _parse_overrides

    with pytest.raises(click.UsageError):
        _parse_overrides(("just-a-key",))


def test_a_dotted_override_layers_over_a_devices_own_vars(workspace: Path) -> None:
    """The override must replace one leaf, not the whole display block."""
    # Arrange
    from fleetctl.cli.main import _parse_overrides
    from fleetctl.core.config.layering import for_device

    device_vars = {"kodi": {"display": {"resolution_index": 18, "overscan": {"left": 0, "right": 1920}}}}

    # Act
    resolved = for_device(device=device_vars, flags=_parse_overrides(("kodi.display.overscan.right=1900",)))

    # Assert
    assert resolved.values["kodi"]["display"]["overscan"] == {"left": 0, "right": 1900}
    assert resolved.values["kodi"]["display"]["resolution_index"] == 18


def test_a_confirm_verdict_stops_a_single_step_run(workspace: Path) -> None:
    """`workflow run` has always honoured approval; a single step ignoring it
    made `confirm:` decorative on the shortest path to a destructive change."""
    # Arrange
    (workspace / "config" / "fleet.yml").write_text(
        "observability:\n  audit_dir: audit\npolicy:\n  actors:\n    '*':\n      allow: ['*']\n      confirm: [destructive]\n", encoding="utf-8"
    )

    # Act
    refused = _invoke(workspace, "run", "firetv.maintain", "--device", "stick-1")

    # Assert
    assert refused.exit_code != 0
    assert "--approve" in refused.output
