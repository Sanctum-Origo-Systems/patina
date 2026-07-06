#!/usr/bin/env python3
"""Read the Patina version from pyproject.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent


def get_version() -> str:
    """Return the version string from pyproject.toml."""
    pyproject = REPO_DIR / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    return data["project"]["version"]
