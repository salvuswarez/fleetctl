"""Executable enforcement of the ring rule.

The inward-only dependency rule is the single highest-consequence invariant
in this codebase, and until now it was enforced by a slash command someone
had to remember to run. This makes it part of the gate.

Deliberately AST-based rather than import-based: it holds when `packs/` and
`apps/` do not exist yet, needs no extra dependency, and reports the exact
file and line rather than a resolution error.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from typing import Iterator

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "fleetctl"

# Shared collaborator libraries composed by vendor packs. Each registers
# nothing and has no entry point, which is what makes it a base rather than a
# sibling — these are the only intra-ring imports permitted, see
# docs/pack-authoring.md. A pack with an entry point never belongs here.
SHARED_PACKS = ("fleetctl.packs.android", "fleetctl.packs.posix")

# Device and app vocabulary that must never appear in the kernel. A hit here
# usually means a vendor quirk leaked inward; it belongs to the pack that has
# the quirk, as data.
FORBIDDEN_IN_CORE = ("kodi", "firetv", "fire_tv", "shield", "amazon", "xbmc", "adb", "toybox")


def _modules(ring: str) -> Iterator[tuple[Path, ast.Module]]:
    root = SRC / ring
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*.py")):
        yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_names(tree: ast.Module, path: Path) -> Iterator[tuple[int, str]]:
    """Yield `(lineno, dotted_name)` for every import, absolute or relative.

    Relative imports are resolved against the importing module's own package.
    Skipping them, as an earlier version of this did, left the widest hole
    possible: `from ...packs.android import actions` inside an app pack is
    exactly the violation these tests exist to catch, and it sailed straight
    through.
    """
    package = _package_of(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    yield node.lineno, node.module
            else:
                yield node.lineno, _resolve_relative(package, node.level, node.module)


def _package_of(path: Path) -> list[str]:
    """RETURNS: list[str]: The dotted package parts of the module at `path`."""
    relative = path.relative_to(SRC.parent)
    parts = list(relative.parts[:-1]) if relative.name == "__init__.py" else list(relative.parts[:-1])
    return parts


def _resolve_relative(package: list[str], level: int, module: str | None) -> str:
    """RETURNS: str: A relative import resolved to its absolute dotted name."""
    base = package[: len(package) - (level - 1)] if level > 1 else package
    return ".".join([*base, *([module] if module else [])])


def test_core_does_not_import_packs_or_apps() -> None:
    # Arrange / Act
    violations = [
        f"{path}:{lineno} imports {name}"
        for path, tree in _modules("core")
        for lineno, name in _imported_names(tree, path)
        if name.startswith(("fleetctl.packs", "fleetctl.apps"))
    ]

    # Assert
    assert violations == [], "core/ must not depend on packs/ or apps/:\n" + "\n".join(violations)


def test_apps_do_not_import_packs() -> None:
    """An app pack declares the capabilities it needs; the engine resolves
    the provider. Importing a device pack defeats the whole design."""
    # Arrange / Act
    violations = [
        f"{path}:{lineno} imports {name}"
        for path, tree in _modules("apps")
        for lineno, name in _imported_names(tree, path)
        if name.startswith("fleetctl.packs")
    ]

    # Assert
    assert violations == [], "apps/ must not depend on packs/:\n" + "\n".join(violations)


def test_packs_do_not_import_apps() -> None:
    # Arrange / Act
    violations = [
        f"{path}:{lineno} imports {name}"
        for path, tree in _modules("packs")
        for lineno, name in _imported_names(tree, path)
        if name.startswith("fleetctl.apps")
    ]

    # Assert
    assert violations == [], "packs/ must not depend on apps/:\n" + "\n".join(violations)


def test_a_pack_imports_no_sibling_pack_except_a_shared_base() -> None:
    # Arrange / Act
    violations = []
    for path, tree in _modules("packs"):
        own = f"fleetctl.packs.{path.relative_to(SRC / 'packs').parts[0]}"
        for lineno, name in _imported_names(tree, path):
            if name.startswith("fleetctl.packs.") and not name.startswith((own, *SHARED_PACKS)):
                violations.append(f"{path}:{lineno} imports {name}")

    # Assert
    assert violations == [], f"a pack may only compose {' or '.join(SHARED_PACKS)}:\n" + "\n".join(violations)


def test_no_shared_base_is_registered_as_a_pack() -> None:
    """A shared base is exempt from the sibling-import rule. If one also had
    an entry point it would be a vendor pack too, and the exemption would
    quietly become a hole any pack could import through."""
    # Arrange
    pyproject = (SRC.parents[1] / "pyproject.toml").read_text(encoding="utf-8")

    # Act
    registered = [base for base in SHARED_PACKS if f"{base}.pack:" in pyproject]

    # Assert
    assert registered == [], "these shared bases are registered as packs:\n" + "\n".join(registered)


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """Return the `id()` of every string node used as a docstring.

    Prose explaining *why* the kernel is shaped a certain way legitimately
    names devices — the rule is about coupling, not about vocabulary.
    """
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


@pytest.mark.parametrize("term", FORBIDDEN_IN_CORE)
def test_core_code_is_free_of_device_vocabulary(term: str) -> None:
    """Catches the leak the effect-class design exists to prevent: a kernel
    that classifies commands by recognizing `pm` or `getprop`.

    Checks identifiers and runtime string literals only. Docstrings and
    comments are exempt — the predecessor's hard-won reasons for these
    designs are worth writing down inside the modules they shaped.
    """
    # Arrange / Act
    hits = []
    for path, tree in _modules("core"):
        docstrings = _docstring_nodes(tree)
        for node in ast.walk(tree):
            candidate: str | None = None
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                candidate = node.value
            elif isinstance(node, ast.Name):
                candidate = node.id
            elif isinstance(node, ast.Attribute):
                candidate = node.attr
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                candidate = node.name
            if candidate and term in candidate.lower():
                hits.append(f"{path}:{getattr(node, 'lineno', 0)}: {candidate!r}")

    # Assert
    assert hits == [], f"core/ code must not reference {term!r}:\n" + "\n".join(hits)


def test_every_source_package_is_tracked_by_git() -> None:
    """A `.gitignore` rule caught a whole source package once.

    `config/` was written unanchored, so it matched `src/fleetctl/core/config/`
    as well as the repository-root directory it was meant for, and four
    modules were silently never committed — a fresh clone would not import.
    Directory rules are anchored now; this makes the mistake loud rather than
    silent if one slips through again.

    Skipped outside a git checkout, since a source tarball is a legitimate
    way to run the suite.
    """
    # Arrange
    try:
        result = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            cwd=SRC.parents[1],
            input="\n".join(str(path) for path in sorted(SRC.rglob("*.py"))),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git is not available here")
    # 0 means "something matched an ignore rule"; 1 means nothing did.
    if result.returncode not in (0, 1):
        pytest.skip("not a git checkout")

    # Assert
    ignored = [line for line in result.stdout.splitlines() if line.strip()]
    assert ignored == [], "these source files are excluded by .gitignore:\n" + "\n".join(ignored)
