"""Shared pytest fixtures.

The suite runs headless (QT_QPA_PLATFORM=offscreen) and against real rsync
where available, so it works on dev machines and CI alike.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# make the repo importable no matter how pytest is invoked
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session (offscreen)."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def cfg_dir(tmp_path, monkeypatch):
    """Isolate config + history in a temporary directory."""
    from sentinel import config
    monkeypatch.setattr(config, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_FILE", str(tmp_path / "config.json"))
    return tmp_path
