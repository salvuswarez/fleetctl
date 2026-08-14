"""YAML loading that understands `!ref`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from fleetctl.core.config.secrets import SecretRef
from fleetctl.core.errors import ConfigError


class FleetLoader(yaml.SafeLoader):
    """Safe YAML loader that additionally understands the `!ref` tag."""


def _construct_ref(loader: yaml.SafeLoader, node: yaml.Node) -> SecretRef:
    """Build a `SecretRef` from a `!ref scheme:locator` node.

    **RAISES:**
        `ConfigError`: If the node is not a scalar, or is not `scheme:locator`.  <br>
    """
    if not isinstance(node, yaml.ScalarNode):
        raise ConfigError("!ref must be a scalar like 'env:FLEETCTL_SMB_PASS'")
    raw = str(loader.construct_scalar(node)).strip()
    scheme, separator, locator = raw.partition(":")
    if not separator or not scheme or not locator.strip():
        raise ConfigError(f"!ref must be 'scheme:locator', got {raw!r}")
    return SecretRef(scheme=scheme.strip().lower(), locator=locator.strip())


FleetLoader.add_constructor("!ref", _construct_ref)


def load_yaml_text(text: str, *, source: str = "<string>") -> dict[str, Any]:
    """Parse YAML that may contain `!ref` tags.

    **PARAMETERS:**
        `text` (str): YAML document.  <br>
        `source` (str): Name used in error messages.  <br>

    **RETURNS:**
        `dict[str, Any]`: The parsed mapping, or an empty dict if the document is empty or not a mapping.  <br>

    **RAISES:**
        `ConfigError`: If the document is malformed.  <br>
    """
    try:
        loaded = yaml.load(text, Loader=FleetLoader)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Could not parse {source}: {exc}", key=source) from exc
    return loaded if isinstance(loaded, dict) else {}


def load_yaml_file(path: Path) -> dict[str, Any]:
    """Parse a YAML file that may contain `!ref` tags.

    **PARAMETERS:**
        `path` (Path): File to read.  <br>

    **RETURNS:**
        `dict[str, Any]`: The parsed mapping, or an empty dict if the file does not exist.  <br>

    **RAISES:**
        `ConfigError`: If the file cannot be read or is malformed.  <br>
    """
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Could not read {path}: {exc}", key=str(path)) from exc
    return load_yaml_text(text, source=str(path))
