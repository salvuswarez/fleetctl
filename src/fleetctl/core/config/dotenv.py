"""Reading a `.env` file into the environment, for `!ref env:` to resolve."""

from __future__ import annotations

import logging
import os
from pathlib import Path

LOGGER = logging.getLogger(__name__)


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse `KEY=VALUE` lines.

    Deliberately small: no interpolation, no `export` prefixes, no multi-line
    values. A secret that needs those belongs in a secret manager, behind a
    different `!ref` scheme.

    **PARAMETERS:**
        `text` (str): File contents.  <br>

    **RETURNS:**
        `dict[str, str]`: Parsed pairs. Blank lines, comments, and lines without `=` are skipped. Surrounding quotes are stripped.  <br>
    """
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_dotenv(path: Path) -> int:
    """Load `path` into the environment, leaving anything already set alone.

    The real environment wins so a shell or a container can override the file
    without editing it.

    **PARAMETERS:**
        `path` (Path): The `.env` file. A missing file is not an error.  <br>

    **RETURNS:**
        `int`: How many variables were set.  <br>
    """
    if not path.is_file():
        return 0
    try:
        values = parse_dotenv(path.read_text(encoding="utf-8"))
    except OSError as exc:
        LOGGER.warning("Could not read %s: %s", path, exc)
        return 0

    applied = 0
    for key, value in values.items():
        if key not in os.environ:
            os.environ[key] = value
            applied += 1
    # Names only: the values are the reason this file exists.
    LOGGER.debug("Loaded %d variable(s) from %s: %s", applied, path, ", ".join(sorted(values)))
    return applied
