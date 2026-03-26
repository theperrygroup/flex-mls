"""Tests for version metadata consistency."""

from __future__ import annotations

import re
from pathlib import Path

from flex_mls import __version__
from flex_mls.base_client import DEFAULT_USER_AGENT

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_pyproject_version() -> str:
    """Read the package version declared in ``pyproject.toml``.

    Returns:
        The version string declared in project metadata.

    Raises:
        AssertionError: If the version cannot be located.
    """

    pyproject_text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', pyproject_text, re.MULTILINE)
    assert match is not None, "Expected a project version in pyproject.toml."
    return match.group(1)


def test_package_version_matches_pyproject_metadata() -> None:
    """The runtime package version matches the packaging metadata version."""

    assert __version__ == _read_pyproject_version()


def test_default_user_agent_tracks_the_package_version() -> None:
    """The default user agent embeds the current package version."""

    assert DEFAULT_USER_AGENT.endswith(f"/{__version__}")
