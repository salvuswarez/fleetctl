"""Redaction, applied before anything is written.

Two lessons from the predecessor drive this. Its `SmbConfig` was a dataclass
holding a plaintext password with no `repr=False`, so any log of the config
object would have printed the credential. And its ADB layer logged full
command strings at debug level, while device settings routinely carry
credential-bearing URLs (an IPTV playlist URL with `username=`/`password=`
embedded is the common case).

Neither was a bug anyone had written yet. Both were one careless line away,
which is why this is a type applied at a chokepoint rather than a rule
people are asked to remember.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

MASK = "***REDACTED***"

# Ordered most-specific first. Each pattern keeps the identifying prefix so a
# redacted record still says *what* was removed.
_DEFAULT_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Credentials embedded in a URL: scheme://user:secret@host
    re.compile(r"(?P<keep>[a-zA-Z][a-zA-Z0-9+.-]*://[^\s:/@]+:)[^\s@]+(?P<tail>@)"),
    # Query-string credentials: ?password=... &token=...
    re.compile(r"(?P<keep>[?&](?:password|passwd|pwd|token|api_key|apikey|secret|auth)=)[^\s&\"']+", re.IGNORECASE),
    # Assignment forms: password=..., token: ...
    re.compile(r"(?P<keep>\b(?:password|passwd|pwd|token|secret|api_key|apikey)\b\s*[:=]\s*)(?!\!ref\b)[^\s,;\"']+", re.IGNORECASE),
    # Env-var style: FLEETCTL_SMB_PASS=..., MY_API_TOKEN=... The word-boundary
    # forms above miss these because `_` is a word character.
    re.compile(
        r"(?P<keep>\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)*_(?:PASS|PASSWD|PASSWORD|SECRET|TOKEN|KEY|APIKEY|API_KEY)\s*=\s*)(?!\!ref\b)[^\s,;\"']+",
        re.IGNORECASE,
    ),
    # Known credential shapes.
    re.compile(r"(?P<keep>)\bgithub_pat_[A-Za-z0-9_]+"),
    re.compile(r"(?P<keep>)\bghp_[A-Za-z0-9]{20,}"),
    re.compile(r"(?P<keep>-----BEGIN [A-Z ]*PRIVATE KEY-----)[\s\S]*?(?P<tail>-----END [A-Z ]*PRIVATE KEY-----)"),
)

_DEFAULT_SENSITIVE_KEYS: frozenset[str] = frozenset({"password", "passwd", "pwd", "secret", "token", "api_key", "apikey", "auth", "credential", "private_key"})


@dataclass(frozen=True, slots=True)
class Redactor:
    """Removes credential-shaped content from text and structured records.

    Pure: text in, text out. That makes the leak paths it closes directly
    testable, which is the point — a redactor nobody can test is a redactor
    nobody trusts.

    **PARAMETERS:**
        `patterns` (Sequence[re.Pattern[str]]): Regexes whose match is replaced, preserving any `keep` and `tail` groups.  <br>
        `sensitive_keys` (frozenset[str]): Mapping keys whose values are masked wholesale, matched case-insensitively against the final path segment.  <br>
    """

    patterns: Sequence[re.Pattern[str]] = field(default=_DEFAULT_PATTERNS)
    sensitive_keys: frozenset[str] = field(default=_DEFAULT_SENSITIVE_KEYS)

    def text(self, value: str) -> str:
        """Mask credential-shaped substrings in free text.

        **PARAMETERS:**
            `value` (str): Text that may contain credentials, such as a shell command.  <br>

        **RETURNS:**
            `str`: The text with any matches replaced by `MASK`.  <br>
        """
        result = value
        for pattern in self.patterns:
            result = pattern.sub(self._replace, result)
        return result

    def mapping(self, value: Mapping[str, Any]) -> dict[str, Any]:
        """Mask sensitive values in a structured record, recursively.

        A key match masks the whole value; every other string is still run
        through `text`, so a credential hiding inside an innocuously-named
        field is caught too.

        **PARAMETERS:**
            `value` (Mapping[str, Any]): Record to redact.  <br>

        **RETURNS:**
            `dict[str, Any]`: A redacted copy. The input is never mutated.  <br>
        """
        return {key: self._value(key, item) for key, item in value.items()}

    def _value(self, key: str, item: Any) -> Any:
        if key.rsplit(".", 1)[-1].lower() in self.sensitive_keys:
            return MASK
        if isinstance(item, str):
            return self.text(item)
        if isinstance(item, Mapping):
            return self.mapping(item)
        if isinstance(item, (list, tuple)):
            return [self._value(key, entry) for entry in item]
        return item

    @staticmethod
    def _replace(match: re.Match[str]) -> str:
        groups = match.groupdict()
        return f"{groups.get('keep') or ''}{MASK}{groups.get('tail') or ''}"
