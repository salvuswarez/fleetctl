"""Effect classification and the capability vocabulary."""

from __future__ import annotations

from enum import Enum


class Effect(str, Enum):
    """How much a single action changes on the target."""

    READ = "read"
    MUTATING = "mutating"
    DESTRUCTIVE = "destructive"

    @property
    def is_auditable(self) -> bool:
        """RETURNS: bool: Whether this effect belongs in the durable audit trail."""
        return self is not Effect.READ


class Capability(str, Enum):
    """What a device pack promises it can do, and a step declares it needs."""

    REACH = "reach"
    FACTS = "facts"
    EXEC = "exec"
    FILES = "files"
    APPS = "apps"
    SETTINGS = "settings"
    POWER = "power"
    STATE = "state"
    CLEANUP = "cleanup"


# Verbs the connection itself performs, so the transport is the only honest
# answer for them. The rest — state, apps, settings, cleanup — are built on
# these by a pack's managers, and whether a pack has one is a property of the
# pack, not of the wire.
WIRE_CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.REACH,
        Capability.FACTS,
        Capability.EXEC,
        Capability.FILES,
        Capability.POWER,
    }
)


def missing_capabilities(required: frozenset[Capability], provided: frozenset[Capability]) -> frozenset[Capability]:
    """Report which required capabilities a provider does not offer.

    **PARAMETERS:**
        `required` (frozenset[Capability]): What a step needs.  <br>
        `provided` (frozenset[Capability]): What the resolved pack/transport offers.  <br>

    **RETURNS:**
        `frozenset[Capability]`: The unsatisfied subset; empty when the step can run.  <br>
    """
    return frozenset(required - provided)
