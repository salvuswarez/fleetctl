"""Per-operation staging directories, and keeping the evidence when work fails."""

from __future__ import annotations

import logging
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

LOGGER = logging.getLogger(__name__)

_MAX_KEPT_FAILURES = 20


@contextmanager
def workspace(root: Path, op_id: str, *, failures_root: Path | None = None) -> Generator[Path, None, None]:
    """Provide a staging directory scoped to one operation.

    **PARAMETERS:**
        `root` (Path): Parent directory for staging directories.  <br>
        `op_id` (str): Operation id, used to name the directory.  <br>
        `failures_root` (Path | None, optional): Where to preserve the workspace if the block raises. Defaults to ``None``, meaning discard on failure too.  <br>

    **YIELDS:**
        `Path`: The staging directory. Removed on exit; preserved under `failures_root` first if the block raised.  <br>
    """
    root.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(char if char.isalnum() or char in "-_." else "_" for char in op_id)
    path = Path(tempfile.mkdtemp(prefix=f"{safe_id}_", dir=str(root)))
    try:
        yield path
    except BaseException:
        if failures_root is not None:
            _preserve(path, failures_root, safe_id)
        raise
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _preserve(path: Path, failures_root: Path, op_id: str) -> None:
    """Copy a failed operation's workspace aside, best-effort."""
    try:
        failures_root.mkdir(parents=True, exist_ok=True)
        destination = failures_root / op_id
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        shutil.copytree(path, destination)
        _prune(failures_root)
        LOGGER.info("Preserved failed workspace at %s", destination)
    except OSError as exc:
        LOGGER.warning("Could not preserve workspace for %s: %s", op_id, exc)


def _prune(failures_root: Path) -> None:
    """Keep only the most recent preserved workspaces."""
    kept = sorted((entry for entry in failures_root.iterdir() if entry.is_dir()), key=lambda entry: entry.stat().st_mtime, reverse=True)
    for stale in kept[_MAX_KEPT_FAILURES:]:
        shutil.rmtree(stale, ignore_errors=True)
