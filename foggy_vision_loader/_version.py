"""Resolve the package version from ``pyproject.toml``.

``pyproject.toml`` is the single source of truth.  A source checkout reads it
directly; an installed wheel has no ``pyproject.toml`` beside the package, so
it uses the package metadata generated from that file at build time.
"""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

_DISTRIBUTION = "foggy_vision_loader"


def _version_from_pyproject(pyproject: Path) -> str:
    text = pyproject.read_text(encoding="utf-8")
    project = re.search(r"(?ms)^\[project\]\s*$(.*?)(?=^\[|\Z)", text)
    if project is None:
        raise RuntimeError(f"No [project] section in {pyproject}")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', project.group(1))
    if match is None:
        raise RuntimeError(f"No project version in {pyproject}")
    return match.group(1)


def get_version() -> str:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if pyproject.is_file():
        return _version_from_pyproject(pyproject)
    try:
        return version(_DISTRIBUTION)
    except PackageNotFoundError as exc:
        raise RuntimeError(
            f"Could not determine the {_DISTRIBUTION} version: no pyproject.toml "
            "beside the package and no installed package metadata"
        ) from exc


__version__ = get_version()
