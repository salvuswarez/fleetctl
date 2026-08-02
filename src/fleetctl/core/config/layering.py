"""Layered config resolution — pure, so it can be explained."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

# Ordered lowest-precedence first. Names are surfaced to users by `explain`.
LAYER_ORDER: tuple[str, ...] = ("pack", "fleet", "group", "device", "step", "flags")


@dataclass(frozen=True, slots=True)
class Layer:
    """One contribution to a resolved config.

    **PARAMETERS:**
        `name` (str): Which layer this is; conventionally one of `LAYER_ORDER`.  <br>
        `values` (Mapping[str, Any]): What it contributes.  <br>
        `source` (str): Where it came from, e.g. a file path. Shown by `explain`.  <br>
    """

    name: str
    values: Mapping[str, Any] = field(default_factory=dict)
    source: str = ""


@dataclass(frozen=True, slots=True)
class Resolved:
    """A merged config plus the provenance of every key.

    **PARAMETERS:**
        `values` (Mapping[str, Any]): The merged result.  <br>
        `origins` (Mapping[str, str]): Dotted key path to the layer that won it.  <br>
    """

    values: Mapping[str, Any]
    origins: Mapping[str, str]

    def get(self, path: str, default: Any = None) -> Any:
        """Read a value by dotted path.

        **PARAMETERS:**
            `path` (str): Dotted key path, e.g. ``archive.gzip_separately``.  <br>
            `default` (Any): Returned when the path is absent.  <br>

        **RETURNS:**
            `Any`: The value, or `default`.  <br>
        """
        current: Any = self.values
        for part in path.split("."):
            if not isinstance(current, Mapping) or part not in current:
                return default
            current = current[part]
        return current

    def origin(self, path: str) -> str:
        """RETURNS: str: Which layer supplied `path`, or ``""`` if it was never set."""
        return self.origins.get(path, "")

    def explain(self) -> list[str]:
        """Describe where every value came from, one line per key.

        **RETURNS:**
            `list[str]`: ``key = value  [layer]`` lines, sorted by key. Secrets render masked, since `Secret` does not reveal itself.  <br>
        """
        return [f"{path} = {self.get(path)!s}  [{layer}]" for path, layer in sorted(self.origins.items())]


def _flatten(values: Mapping[str, Any], prefix: str = "") -> Iterable[tuple[str, Any]]:
    for key, value in values.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, Mapping) and value:
            yield from _flatten(value, path)
        else:
            yield path, value


def _deep_merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(dict(existing), value)
        else:
            merged[key] = value
    return merged


def resolve(layers: Sequence[Layer]) -> Resolved:
    """Merge layers in order, recording which one supplied each key.

    **PARAMETERS:**
        `layers` (Sequence[Layer]): Layers, lowest precedence first.  <br>

    **RETURNS:**
        `Resolved`: The merged values plus per-key provenance.  <br>
    """
    values: dict[str, Any] = {}
    origins: dict[str, str] = {}
    for layer in layers:
        if not layer.values:
            continue
        values = _deep_merge(values, layer.values)
        for path, _ in _flatten(layer.values):
            origins[path] = layer.name
    return Resolved(values=values, origins=origins)


def for_device(
    *,
    pack: Mapping[str, Any] | None = None,
    fleet: Mapping[str, Any] | None = None,
    groups: Sequence[Mapping[str, Any]] = (),
    device: Mapping[str, Any] | None = None,
    step: Mapping[str, Any] | None = None,
    flags: Mapping[str, Any] | None = None,
) -> Resolved:
    """Resolve config for one (device, step) pair in the standard order.

    **PARAMETERS:**
        `pack` (Mapping[str, Any] | None): Pack defaults — the lowest layer.  <br>
        `fleet` (Mapping[str, Any] | None): Fleet-wide settings.  <br>
        `groups` (Sequence[Mapping[str, Any]]): Group variables, applied in the order given.  <br>
        `device` (Mapping[str, Any] | None): This device's own variables.  <br>
        `step` (Mapping[str, Any] | None): A workflow step's ``with:`` block.  <br>
        `flags` (Mapping[str, Any] | None): Command-line overrides — the highest layer.  <br>

    **RETURNS:**
        `Resolved`: The merged config with provenance.  <br>
    """
    layers = [Layer("pack", pack or {}), Layer("fleet", fleet or {})]
    layers.extend(Layer("group", group) for group in groups)
    layers.append(Layer("device", device or {}))
    layers.append(Layer("step", step or {}))
    layers.append(Layer("flags", flags or {}))
    return resolve(layers)
