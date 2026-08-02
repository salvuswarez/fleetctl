"""Secret references, and the seam that resolves them.

Config files hold pointers, never values:

    password: !ref env:FLEETCTL_SMB_PASS

Home Assistant's own standard is the model — credentials come from a config
entry and never appear in a YAML file a user edits. Generalized here so each
consumer resolves its own way: the CLI from the environment, Home Assistant
from its config entry, a headless runner from the OS keyring.

The property this buys is concrete: a `fleet.yml` is safe to paste into a
bug report. That matters because the predecessor once leaked real device
data into a committed doc and needed a history rewrite to scrub it.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from ..errors import SecretResolutionError

_REF_PATTERN = re.compile(r"^!ref\s+(?P<scheme>[a-z][a-z0-9_-]*):(?P<locator>.+)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SecretRef:
    """A pointer to a secret held somewhere other than a config file.

    **PARAMETERS:**
        `scheme` (str): Which provider resolves it, e.g. ``env`` or ``keyring``.  <br>
        `locator` (str): Provider-specific name, e.g. an environment variable.  <br>
    """

    scheme: str
    locator: str

    @classmethod
    def parse(cls, value: str) -> SecretRef | None:
        """Parse a `!ref scheme:locator` string.

        **PARAMETERS:**
            `value` (str): Candidate config value.  <br>

        **RETURNS:**
            `SecretRef | None`: The reference, or ``None`` if `value` is an ordinary string.  <br>
        """
        match = _REF_PATTERN.match(value.strip())
        if match is None:
            return None
        return cls(scheme=match.group("scheme").lower(), locator=match.group("locator").strip())

    def __str__(self) -> str:
        """RETURNS: str: The original `!ref` form. Safe to log — it names a location, not a value."""
        return f"!ref {self.scheme}:{self.locator}"


class Secret:
    """A resolved secret that will not render itself.

    `str()` and `repr()` both mask. Reading the value requires calling
    `reveal()` deliberately, which makes the leak paths greppable.

    The predecessor's SMB config was a plain dataclass holding a password
    with no `repr=False`, so any log of that object would have printed the
    credential.

    **PARAMETERS:**
        `value` (str): The secret value.  <br>
        `origin` (str): Where it came from, for diagnostics. Never the value itself.  <br>
    """

    __slots__ = ("_value", "origin")

    def __init__(self, value: str, *, origin: str = "") -> None:
        self._value = value
        self.origin = origin

    def reveal(self) -> str:
        """RETURNS: str: The secret value. Call only at the edge that needs it."""
        return self._value

    def __str__(self) -> str:
        return "**********"

    def __repr__(self) -> str:
        return f"Secret(origin={self.origin!r})"

    def __bool__(self) -> bool:
        return bool(self._value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Secret) and self._value == other._value

    def __hash__(self) -> int:
        return hash(self._value)


class SecretProvider(Protocol):
    """Resolves secret references of one scheme."""

    @property
    def scheme(self) -> str:
        """RETURNS: str: The `!ref` scheme this provider handles."""

    def resolve(self, locator: str) -> Secret | None:
        """RETURNS: Secret | None: The secret, or None if this provider does not have it."""


@dataclass(frozen=True, slots=True)
class EnvSecretProvider:
    """Resolves `!ref env:NAME` from the process environment. Used by the CLI."""

    scheme: str = "env"

    def resolve(self, locator: str) -> Secret | None:
        """RETURNS: Secret | None: The environment variable's value, or None if unset."""
        value = os.environ.get(locator)
        return None if value is None else Secret(value, origin=f"env:{locator}")


@dataclass(frozen=True, slots=True)
class MappingSecretProvider:
    """Resolves references from an in-memory mapping.

    Backs the Home Assistant config-entry provider (whose entry data is a
    mapping) and makes secret resolution testable without touching the
    environment or a keyring.

    **PARAMETERS:**
        `values` (Mapping[str, str]): Locator to secret value.  <br>
        `scheme` (str): The scheme this instance answers for.  <br>
    """

    values: Mapping[str, str]
    scheme: str = "entry"

    def resolve(self, locator: str) -> Secret | None:
        """RETURNS: Secret | None: The mapped value, or None if absent."""
        value = self.values.get(locator)
        return None if value is None else Secret(value, origin=f"{self.scheme}:{locator}")


class SecretResolver:
    """Resolves `!ref` values through registered providers.

    **PARAMETERS:**
        `providers` (tuple[SecretProvider, ...]): Providers, consulted by scheme.  <br>
    """

    def __init__(self, *providers: SecretProvider) -> None:
        self._by_scheme = {provider.scheme: provider for provider in providers}

    def resolve(self, ref: SecretRef) -> Secret:
        """Resolve one reference.

        **PARAMETERS:**
            `ref` (SecretRef): The reference to resolve.  <br>

        **RETURNS:**
            `Secret`: The resolved secret.  <br>

        **RAISES:**
            `SecretResolutionError`: If no provider handles the scheme, or the provider has no such secret. Failing loudly matters — a silently empty credential surfaces later as an unexplained auth failure.  <br>
        """
        provider = self._by_scheme.get(ref.scheme)
        if provider is None:
            raise SecretResolutionError(str(ref))
        secret = provider.resolve(ref.locator)
        if secret is None:
            raise SecretResolutionError(str(ref))
        return secret

    def resolve_all(self, config: Mapping[str, Any]) -> dict[str, Any]:
        """Walk a config tree, replacing every `!ref` string with a `Secret`.

        **PARAMETERS:**
            `config` (Mapping[str, Any]): Config that may contain references.  <br>

        **RETURNS:**
            `dict[str, Any]`: A copy with references resolved. The input is never mutated.  <br>

        **RAISES:**
            `SecretResolutionError`: If any reference cannot be resolved.  <br>
        """
        return {key: self._walk(value) for key, value in config.items()}

    def _walk(self, value: Any) -> Any:
        if isinstance(value, SecretRef):
            return self.resolve(value)
        if isinstance(value, str):
            ref = SecretRef.parse(value)
            return self.resolve(ref) if ref else value
        if isinstance(value, Mapping):
            return self.resolve_all(value)
        if isinstance(value, (list, tuple)):
            return [self._walk(item) for item in value]
        return value
