"""Layering for the pack's YAML definitions."""

from __future__ import annotations

from typing import Any, Mapping


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Layer `override` onto `base`.

    Nested mappings merge key by key, so a variant can change one entry without
    restating the block around it. Everything else — including lists — replaces
    wholesale: a list that silently accumulated its parent's entries could not
    express *removing* one, which is the main reason a variant exists.

    **PARAMETERS:**
        `base` (Mapping[str, Any]): The inherited definition.  <br>
        `override` (Mapping[str, Any]): The extending definition.  <br>

    **RETURNS:**
        `dict[str, Any]`: A new merged mapping. Neither input is mutated.  <br>
    """
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = deep_merge(existing, value)
        else:
            merged[key] = value
    return merged
