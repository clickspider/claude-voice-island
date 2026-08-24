"""Shared fixtures.

Every test runs against a throwaway settings directory. Nothing here can read or
write the settings of the person running the suite.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Point config and logs at a temporary directory for the whole test."""
    monkeypatch.setenv("VOICE_ISLAND_HOME", str(tmp_path / "island"))
    return tmp_path / "island"
