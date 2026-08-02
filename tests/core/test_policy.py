"""Tests for the policy layer."""

from __future__ import annotations

import pytest

from fleetctl.core.effects import Effect
from fleetctl.core.errors import ConfigError
from fleetctl.core.inventory.device import Device
from fleetctl.core.policy import Policy, Verdict, load_policy, permissive

RAW = {
    "protected": [
        {
            "match": {"tags": ["reference"]},
            "deny": ["kodi.deploy", "*.maintain"],
            "reason": "Reference device: prove the change elsewhere first.",
        }
    ],
    "actors": {
        "cli:*": {"allow": ["*"]},
        "ha:*": {"allow": ["*"], "confirm": ["destructive"]},
        "mcp:*": {"allow": ["*"], "confirm": ["mutating", "destructive"], "deny": ["*.factory_reset"], "max_devices": 2},
    },
    "defaults": {"max_devices_per_run": 5},
}


@pytest.fixture
def policy() -> Policy:
    return Policy.from_mapping(RAW)


@pytest.fixture
def reference() -> Device:
    return Device(id="ref-1", type="firetv", tags=["reference", "kodi"])


@pytest.fixture
def ordinary() -> Device:
    return Device(id="spare-1", type="firetv", tags=["kodi"])


def test_an_unconfigured_fleet_is_permissive() -> None:
    """A tool that refuses to work out of the box is a tool nobody configures."""
    # Act
    decision = load_policy({}).check(actor="anyone", step_id="kodi.deploy", effect=Effect.DESTRUCTIVE)

    # Assert
    assert decision.allowed


def test_an_empty_policy_block_is_also_permissive() -> None:
    assert load_policy({"policy": {}}).check(actor="x", step_id="y", effect=Effect.READ).allowed


def test_a_protected_device_is_denied_the_named_step(policy: Policy, reference: Device) -> None:
    # Act
    decision = policy.check(actor="cli:alice", step_id="kodi.deploy", effect=Effect.DESTRUCTIVE, device=reference)

    # Assert
    assert decision.denied
    assert decision.rule == "protected"
    assert "prove the change elsewhere" in decision.reason


def test_protection_outranks_an_otherwise_unrestricted_actor(policy: Policy, reference: Device) -> None:
    """Broadening someone's rights must not reach a protected device."""
    # Act / Assert
    assert policy.check(actor="cli:root", step_id="kodi.deploy", effect=Effect.DESTRUCTIVE, device=reference).denied


def test_protection_patterns_match_by_glob(policy: Policy, reference: Device) -> None:
    # Act / Assert
    assert policy.check(actor="cli:a", step_id="firetv.maintain", effect=Effect.DESTRUCTIVE, device=reference).denied


def test_a_step_outside_the_protection_is_still_allowed(policy: Policy, reference: Device) -> None:
    """Protection is per step, not a blanket quarantine."""
    # Act / Assert
    assert policy.check(actor="cli:a", step_id="kodi.capture", effect=Effect.MUTATING, device=reference).allowed


def test_an_unprotected_device_is_unaffected(policy: Policy, ordinary: Device) -> None:
    assert policy.check(actor="cli:a", step_id="kodi.deploy", effect=Effect.DESTRUCTIVE, device=ordinary).allowed


def test_an_actor_with_no_rule_is_denied(policy: Policy) -> None:
    """An unknown caller getting default access is how a policy layer becomes
    decoration."""
    # Act
    decision = policy.check(actor="unknown:thing", step_id="kodi.capture", effect=Effect.READ)

    # Assert
    assert decision.denied
    assert decision.rule == "no-rule"


def test_confirmation_keys_off_effect_class_not_step_name(policy: Policy, ordinary: Device) -> None:
    """A new destructive step is gated automatically; an allow-list of names
    would have silently permitted it."""
    # Act
    decision = policy.check(actor="ha:automation", step_id="brand.new.step", effect=Effect.DESTRUCTIVE, device=ordinary)

    # Assert
    assert decision.verdict is Verdict.CONFIRM


def test_an_effect_below_the_confirm_threshold_is_allowed(policy: Policy, ordinary: Device) -> None:
    assert policy.check(actor="ha:automation", step_id="kodi.capture", effect=Effect.MUTATING, device=ordinary).allowed


def test_an_agent_needs_approval_for_mutating_work_too(policy: Policy, ordinary: Device) -> None:
    # Act / Assert
    assert policy.check(actor="mcp:claude", step_id="kodi.build", effect=Effect.MUTATING, device=ordinary).verdict is Verdict.CONFIRM


def test_an_explicit_deny_beats_a_wildcard_allow(policy: Policy, ordinary: Device) -> None:
    # Act
    decision = policy.check(actor="mcp:claude", step_id="firetv.factory_reset", effect=Effect.DESTRUCTIVE, device=ordinary)

    # Assert
    assert decision.denied


def test_the_first_matching_actor_rule_wins() -> None:
    # Arrange
    specific = Policy.from_mapping({"actors": {"mcp:trusted": {"allow": ["*"]}, "mcp:*": {"allow": ["*"], "confirm": ["destructive"]}}})

    # Act / Assert
    assert specific.check(actor="mcp:trusted", step_id="x", effect=Effect.DESTRUCTIVE).allowed
    assert specific.check(actor="mcp:other", step_id="x", effect=Effect.DESTRUCTIVE).verdict is Verdict.CONFIRM


def test_blast_radius_uses_the_actors_own_cap(policy: Policy) -> None:
    # Act / Assert
    assert policy.check_blast_radius(actor="mcp:claude", device_count=2).allowed
    assert policy.check_blast_radius(actor="mcp:claude", device_count=3).denied


def test_blast_radius_falls_back_to_the_default(policy: Policy) -> None:
    # Act / Assert
    assert policy.check_blast_radius(actor="cli:alice", device_count=5).allowed
    assert policy.check_blast_radius(actor="cli:alice", device_count=6).denied


def test_the_cap_message_names_the_limit_and_the_overrun(policy: Policy) -> None:
    # Act
    decision = policy.check_blast_radius(actor="mcp:claude", device_count=9)

    # Assert
    assert "at most 2" in decision.reason
    assert "would touch 9" in decision.reason


def test_no_cap_means_unlimited() -> None:
    assert Policy.from_mapping({"actors": {"*": {"allow": ["*"]}}}).check_blast_radius(actor="x", device_count=1000).allowed


def test_a_fleet_level_action_skips_device_protection(policy: Policy) -> None:
    """There is no device to protect."""
    # Act / Assert
    assert policy.check(actor="cli:a", step_id="kodi.build", effect=Effect.MUTATING, device=None).allowed


def test_an_unknown_effect_in_config_is_rejected_with_the_valid_ones() -> None:
    # Act / Assert
    with pytest.raises(ConfigError) as caught:
        Policy.from_mapping({"actors": {"x": {"confirm": ["catastrophic"]}}})
    assert "destructive" in str(caught.value)


@pytest.mark.parametrize("raw", [{"protected": ["not-a-mapping"]}, {"actors": {"x": "not-a-mapping"}}])
def test_a_malformed_policy_is_rejected(raw: dict[str, object]) -> None:
    with pytest.raises(ConfigError):
        Policy.from_mapping(raw)


def test_permissive_allows_every_actor() -> None:
    assert permissive().check(actor="whoever", step_id="anything", effect=Effect.DESTRUCTIVE).allowed
