"""Effect classification and the capability vocabulary.

`Effect` is the highest-consequence declaration in the codebase: the policy
layer decides what needs approval from it, and the observability layer
decides what reaches the durable audit trail from it. A destructive action
labelled `READ` bypasses both.

The default is deliberately `MUTATING` rather than `READ` — an unlabelled
command is audited, not dropped. Under-labelling should cost noise, never
silence.
"""

from __future__ import annotations

from enum import Enum


class Effect(str, Enum):
    """How much a single action changes on the target.

    Ordered by consequence: `READ` < `MUTATING` < `DESTRUCTIVE`.
    """

    READ = "read"
    MUTATING = "mutating"
    DESTRUCTIVE = "destructive"

    @property
    def is_auditable(self) -> bool:
        """RETURNS: bool: Whether this effect belongs in the durable audit trail.

        `READ` goes to the rotating diagnostic log only — a fleet-wide
        maintenance run issues thousands of probe commands, and keeping them
        out of the audit stream is what keeps it reviewable.
        """
        return self is not Effect.READ


class Capability(str, Enum):
    """What a device pack promises it can do, and a step declares it needs.

    Checked at plan time, before anything is touched, so a device that cannot
    satisfy a step is reported rather than half-processed.
    """

    REACH = "reach"
    FACTS = "facts"
    EXEC = "exec"
    FILES = "files"
    APPS = "apps"
    SETTINGS = "settings"
    POWER = "power"
    STATE = "state"
    CLEANUP = "cleanup"


def missing_capabilities(required: frozenset[Capability], provided: frozenset[Capability]) -> frozenset[Capability]:
    """Report which required capabilities a provider does not offer.

    **PARAMETERS:**
        `required` (frozenset[Capability]): What a step needs.  <br>
        `provided` (frozenset[Capability]): What the resolved pack/transport offers.  <br>

    **RETURNS:**
        `frozenset[Capability]`: The unsatisfied subset; empty when the step can run.  <br>
    """
    return frozenset(required - provided)
