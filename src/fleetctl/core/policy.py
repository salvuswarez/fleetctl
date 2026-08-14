"""Who may do what, to which devices."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from fleetctl.core.effects import Effect
from fleetctl.core.errors import ConfigError
from fleetctl.core.inventory.device import Device


class Verdict(str, Enum):
    """What the policy layer decided about one action."""

    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class Decision:
    """A policy outcome, with the reason that produced it.

    **PARAMETERS:**
        `verdict` (Verdict): What was decided.  <br>
        `reason` (str): Why, in words meant for whoever is blocked.  <br>
        `rule` (str): Which rule decided it, for diagnosis.  <br>
    """

    verdict: Verdict
    reason: str = ""
    rule: str = ""

    @property
    def allowed(self) -> bool:
        """RETURNS: bool: Whether this may proceed without further approval."""
        return self.verdict is Verdict.ALLOW

    @property
    def denied(self) -> bool:
        """RETURNS: bool: Whether this is refused outright."""
        return self.verdict is Verdict.DENY


@dataclass(frozen=True, slots=True)
class ProtectedRule:
    """Devices that named steps must never touch.

    **PARAMETERS:**
        `tags` (tuple[str, ...]): Every tag a device must carry to match.  <br>
        `ids` (tuple[str, ...]): Explicit device ids this covers.  <br>
        `deny` (tuple[str, ...]): Step id patterns denied on matching devices. ``*`` denies everything.  <br>
        `reason` (str): Shown when this rule blocks something.  <br>
    """

    tags: tuple[str, ...] = ()
    ids: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()
    reason: str = ""

    def matches(self, device: Device) -> bool:
        """RETURNS: bool: Whether this rule covers `device`."""
        if self.ids and device.id in self.ids:
            return True
        return bool(self.tags) and all(device.has_tag(tag) for tag in self.tags)

    def denies(self, step_id: str) -> bool:
        """RETURNS: bool: Whether this rule denies `step_id`."""
        return any(fnmatch.fnmatch(step_id, pattern) for pattern in self.deny)


@dataclass(frozen=True, slots=True)
class ActorRule:
    """What one class of caller may do.

    **PARAMETERS:**
        `pattern` (str): Actor glob, e.g. ``mcp:*``.  <br>
        `allow` (tuple[str, ...]): Step id patterns this actor may invoke at all.  <br>
        `deny` (tuple[str, ...]): Step id patterns refused outright.  <br>
        `confirm` (tuple[Effect, ...]): Effect classes needing explicit approval.  <br>
        `max_devices` (int): Blast-radius cap for one run; ``0`` means unlimited.  <br>
    """

    pattern: str
    allow: tuple[str, ...] = ("*",)
    deny: tuple[str, ...] = ()
    confirm: tuple[Effect, ...] = ()
    max_devices: int = 0

    def matches(self, actor: str) -> bool:
        """RETURNS: bool: Whether this rule governs `actor`."""
        return fnmatch.fnmatch(actor, self.pattern)


@dataclass(frozen=True, slots=True)
class Policy:
    """The resolved policy for a fleet.

    **PARAMETERS:**
        `protected` (tuple[ProtectedRule, ...]): Device protections, checked before anything else.  <br>
        `actors` (tuple[ActorRule, ...]): Per-actor rules, first match wins.  <br>
        `default_max_devices` (int): Blast-radius cap when an actor rule sets none.  <br>
    """

    protected: tuple[ProtectedRule, ...] = ()
    actors: tuple[ActorRule, ...] = ()
    default_max_devices: int = 0

    def rule_for(self, actor: str) -> ActorRule | None:
        """RETURNS: ActorRule | None: The first rule matching `actor`, if any."""
        return next((rule for rule in self.actors if rule.matches(actor)), None)

    def check(self, *, actor: str, step_id: str, effect: Effect, device: Device | None = None) -> Decision:
        """Decide whether one action may proceed.

        **PARAMETERS:**
            `actor` (str): Who is asking, e.g. ``cli:alice`` or ``mcp:claude``.  <br>
            `step_id` (str): The step being invoked.  <br>
            `effect` (Effect): How much it changes.  <br>
            `device` (Device | None): The target, or None for fleet-level work.  <br>

        **RETURNS:**
            `Decision`: The verdict and the reason for it.  <br>
        """
        if device is not None:
            for rule in self.protected:
                if rule.matches(device) and rule.denies(step_id):
                    reason = rule.reason.strip() or f"{device.id} is protected against {step_id}"
                    return Decision(Verdict.DENY, reason=reason, rule="protected")

        actor_rule = self.rule_for(actor)
        if actor_rule is None:
            # No rule means no grant. An unknown caller getting default access
            # is how a policy layer becomes decoration.
            return Decision(Verdict.DENY, reason=f"No policy rule covers actor {actor!r}", rule="no-rule")

        if any(fnmatch.fnmatch(step_id, pattern) for pattern in actor_rule.deny):
            return Decision(Verdict.DENY, reason=f"{actor} is denied {step_id}", rule=f"actor:{actor_rule.pattern}")

        if not any(fnmatch.fnmatch(step_id, pattern) for pattern in actor_rule.allow):
            return Decision(Verdict.DENY, reason=f"{actor} is not allowed {step_id}", rule=f"actor:{actor_rule.pattern}")

        if effect in actor_rule.confirm:
            return Decision(Verdict.CONFIRM, reason=f"{step_id} is {effect.value}; {actor} requires approval", rule=f"actor:{actor_rule.pattern}")

        return Decision(Verdict.ALLOW, rule=f"actor:{actor_rule.pattern}")

    def check_blast_radius(self, *, actor: str, device_count: int) -> Decision:
        """Check how many devices one run may touch.

        **PARAMETERS:**
            `actor` (str): Who is asking.  <br>
            `device_count` (int): How many devices the run would touch.  <br>

        **RETURNS:**
            `Decision`: Allowed, or denied with the cap that was exceeded.  <br>
        """
        rule = self.rule_for(actor)
        cap = (rule.max_devices if rule and rule.max_devices else 0) or self.default_max_devices
        if cap and device_count > cap:
            return Decision(
                Verdict.DENY,
                reason=f"{actor} may touch at most {cap} device(s) in one run; this run would touch {device_count}",
                rule="blast-radius",
            )
        return Decision(Verdict.ALLOW, rule="blast-radius")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> Policy:
        """Build a policy from a `fleet.yml` `policy:` block.

        **PARAMETERS:**
            `raw` (Mapping[str, Any]): The parsed block.  <br>

        **RETURNS:**
            `Policy`: The parsed policy.  <br>

        **RAISES:**
            `ConfigError`: If a rule is malformed or names an unknown effect class.  <br>
        """
        protected = tuple(_protected_rule(entry) for entry in raw.get("protected", ()))
        actors = tuple(_actor_rule(pattern, entry) for pattern, entry in (raw.get("actors", {}) or {}).items())
        defaults = raw.get("defaults", {}) or {}
        return cls(protected=protected, actors=actors, default_max_devices=int(defaults.get("max_devices_per_run", 0)))


def _protected_rule(entry: Any) -> ProtectedRule:
    if not isinstance(entry, Mapping):
        raise ConfigError("each policy.protected entry must be a mapping", key="policy.protected")
    match = entry.get("match", {}) or {}
    return ProtectedRule(
        tags=tuple(match.get("tags", ())),
        ids=tuple(match.get("ids", ())),
        deny=tuple(entry.get("deny", ())),
        reason=str(entry.get("reason", "")),
    )


def _actor_rule(pattern: str, entry: Any) -> ActorRule:
    if not isinstance(entry, Mapping):
        raise ConfigError(f"policy.actors.{pattern} must be a mapping", key=f"policy.actors.{pattern}")
    return ActorRule(
        pattern=str(pattern),
        allow=tuple(entry.get("allow", ("*",))),
        deny=tuple(entry.get("deny", ())),
        confirm=tuple(_effect(value, pattern) for value in entry.get("confirm", ())),
        max_devices=int(entry.get("max_devices", 0)),
    )


def _effect(value: Any, pattern: str) -> Effect:
    try:
        return Effect(str(value).lower())
    except ValueError as exc:
        known = ", ".join(effect.value for effect in Effect)
        raise ConfigError(f"policy.actors.{pattern}.confirm: unknown effect {value!r} (known: {known})", key=f"policy.actors.{pattern}") from exc


def permissive() -> Policy:
    """A policy that allows everything, for a fleet with no `policy:` block.

    **RETURNS:**
        `Policy`: Allows every actor every step.  <br>
    """
    return Policy(actors=(ActorRule(pattern="*"),))


def load_policy(config: Mapping[str, Any]) -> Policy:
    """Read the `policy:` block from fleet configuration.

    **PARAMETERS:**
        `config` (Mapping[str, Any]): Resolved fleet configuration.  <br>

    **RETURNS:**
        `Policy`: The configured policy, or a permissive one when no block is present.  <br>
    """
    raw = config.get("policy")
    if not isinstance(raw, Mapping) or not raw:
        return permissive()
    return Policy.from_mapping(raw)
