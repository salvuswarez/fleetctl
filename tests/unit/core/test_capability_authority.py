"""Who answers for a capability: the transport, or the pack.

A transport carries the wire verbs. `state` and `apps` are built on exec and
files by the pack's own managers, so one shared transport cannot answer for
every pack that uses it.
"""

from __future__ import annotations

import pytest

from fleetctl.core.effects import Capability, Effect
from fleetctl.core.errors import FleetError
from fleetctl.core.transport.fake import FakeTransport
from fleetctl.core.workflow.runner import check_capabilities
from fleetctl.core.workflow.step import StepSpec
from fleetctl.packs.linux_host.pack import LinuxHostPack
from fleetctl.packs.posix.transport import CAPABILITIES as SSH_CAPABILITIES
from fleetctl.packs.steamdeck.pack import SteamDeckPack

NEEDS_STATE = StepSpec(
    id="kodi.capture",
    summary="Capture a profile.",
    effect=Effect.MUTATING,
    requires=frozenset({Capability.EXEC, Capability.STATE}),
    scope="device",
)


def _ssh_like() -> FakeTransport:
    """RETURNS: FakeTransport: A transport declaring exactly what SSH does."""
    return FakeTransport(supported=SSH_CAPABILITIES)


def test_the_ssh_transport_alone_cannot_satisfy_a_state_step() -> None:
    """It carries no state verb, and correctly does not claim one."""
    # Act / Assert
    with pytest.raises(FleetError, match="state"):
        check_capabilities(NEEDS_STATE, _ssh_like())


def test_a_pack_with_a_state_manager_satisfies_it() -> None:
    """The Steam Deck pack supplies one, so the step can run — checking the
    transport alone rejected a capture the pack could perform."""
    # Act / Assert
    check_capabilities(NEEDS_STATE, _ssh_like(), provided_by_pack=SteamDeckPack.capabilities)


def test_a_pack_without_one_still_fails() -> None:
    """The same transport serves both packs, which is exactly why it cannot be
    the authority: a generic Linux host has no state manager."""
    # Act / Assert
    with pytest.raises(FleetError, match="state"):
        check_capabilities(NEEDS_STATE, _ssh_like(), provided_by_pack=LinuxHostPack.capabilities)


def test_a_transport_limit_is_still_honoured() -> None:
    """A pack's declaration must not paper over a connection that genuinely
    cannot execute anything."""
    # Arrange
    crippled = FakeTransport(supported=frozenset({Capability.REACH}))

    # Act / Assert
    with pytest.raises(FleetError, match="exec"):
        check_capabilities(NEEDS_STATE, crippled, provided_by_pack=SteamDeckPack.capabilities)


def test_the_error_names_every_missing_capability() -> None:
    # Arrange
    bare = FakeTransport(supported=frozenset({Capability.REACH}))

    # Act / Assert
    with pytest.raises(FleetError, match="exec, state"):
        check_capabilities(NEEDS_STATE, bare)


def test_omitting_the_pack_leaves_the_transport_as_sole_authority() -> None:
    """Direct transport tests pass no pack and must keep their meaning."""
    # Arrange
    full = FakeTransport()

    # Act / Assert
    check_capabilities(NEEDS_STATE, full)
