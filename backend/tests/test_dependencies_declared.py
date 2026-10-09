"""Every package the application imports must be in `requirements.txt`.

A deploy died at import time on `ModuleNotFoundError: No module named 'cryptography'`.
The package was installed by hand in the development environment and declared nowhere, so
everything passed locally - 928 tests, a clean build - and the first container to be built
from the declared dependencies could not start.

Nothing here caught it. `test_requirements_coverage.py` is about the product brief's
*fields*; the word "requirements" means something else in that file.

This compares what the code imports against what the file declares, using the installed
metadata rather than a hand-written module-to-package map: `packages_distributions()`
knows that `jwt` comes from PyJWT and `bs4` from beautifulsoup4, and it stays right when a
package renames its import.
"""

from __future__ import annotations

import ast
import re
import sys
from importlib.metadata import packages_distributions
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
REQUIREMENTS = BACKEND / "requirements.txt"

#: Distributions whose import name differs from nothing we can resolve - none today, but
#: the hook is here so a future exception is declared rather than silently skipped.
ALLOWED_UNDECLARED: frozenset[str] = frozenset()


def _normalise(name: str) -> str:
    """PEP 503 names: case-insensitive, and - _ . are the same character."""
    return re.sub(r"[-_.]+", "-", name).lower()


def declared_distributions() -> set[str]:
    names = set()
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        # `uvicorn[standard]==0.52.4` -> uvicorn
        name = re.split(r"[\[=<>!~;]", line, maxsplit=1)[0].strip()
        if name:
            names.add(_normalise(name))
    return names


def imported_top_level_modules() -> dict[str, set[Path]]:
    """Every top-level module name `app/` imports, and where from."""
    found: dict[str, set[Path]] = {}
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                # A relative import is this package, not a dependency.
                names = [node.module] if node.level == 0 and node.module else []
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                found.setdefault(top, set()).add(path.relative_to(BACKEND))
    return found


def third_party_imports() -> dict[str, set[Path]]:
    stdlib = set(sys.stdlib_module_names)
    return {
        module: paths
        for module, paths in imported_top_level_modules().items()
        if module not in stdlib and module != "app"
    }


def test_every_imported_package_is_declared():
    """The check that would have turned a failed deploy into a failed test."""
    distributions = packages_distributions()
    declared = declared_distributions()

    missing: list[str] = []
    for module, paths in sorted(third_party_imports().items()):
        providers = distributions.get(module)
        if not providers:
            # Importable but not from an installed distribution: a local module that is
            # not under `app/`, or a namespace package. Nothing to declare.
            continue
        if any(_normalise(p) in declared for p in providers):
            continue
        if any(_normalise(p) in ALLOWED_UNDECLARED for p in providers):
            continue
        where = ", ".join(str(p) for p in sorted(paths)[:3])
        missing.append(f"{module} (from {' or '.join(providers)}) imported by {where}")

    assert not missing, "imported but not in requirements.txt:\n  " + "\n  ".join(missing)


def test_cryptography_specifically():
    """The one that failed, pinned by name so the regression is unmistakable."""
    assert "cryptography" in declared_distributions()


def test_the_scan_actually_finds_imports():
    """A scanner that silently finds nothing would pass for ever."""
    imports = third_party_imports()
    assert len(imports) > 10
    for expected in ("fastapi", "sqlalchemy", "pydantic"):
        assert expected in imports


@pytest.mark.parametrize("pinned", ["fastapi", "SQLAlchemy", "uvicorn[standard]"])
def test_requirements_are_pinned(pinned: str):
    """An unpinned dependency makes the deployed build different from the tested one."""
    name = re.split(r"[\[=<>!~;]", pinned, maxsplit=1)[0]
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and _normalise(re.split(r"[\[=<>!~;]", line, maxsplit=1)[0]) == _normalise(name):
            assert "==" in line, f"{name} is not pinned: {line!r}"
            return
    pytest.fail(f"{name} is not in requirements.txt at all")
