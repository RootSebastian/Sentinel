"""Updater tests - all offline (network and pip are mocked).

These cover the risky logic: version comparison, the GitHub URL/origin
parsing, install-mode detection and the check pipeline. The one-click
install itself is exercised by hand (it runs pip against GitHub).
"""

import io
import json
import urllib.error

import pytest

from sentinel import updater


# ------------------------------------------------------------ version math --

@pytest.mark.parametrize("remote,local,expected", [
    ("1.3.0", "1.2.1", True),
    ("v1.3.0", "1.2.1", True),
    ("1.2.2", "1.2.1", True),
    ("2.0", "1.9.9", True),          # short versions are padded
    ("1.2.1", "1.2.1", False),       # same version
    ("1.2.0", "1.2.1", False),       # older
    ("1.2.1-beta", "1.2.1", False),  # never "upgrade" to a pre-release
    ("1.2.1", "1.2.1-beta", True),   # final release replaces its beta
    ("1.2.1", "1.3.0", False),
])
def test_is_newer(remote, local, expected):
    assert updater.is_newer(remote, local) is expected


@pytest.mark.parametrize("raw,core,pre", [
    ("1.2.1", (1, 2, 1), False),
    ("v1.2.1", (1, 2, 1), False),
    ("1.2", (1, 2, 0), False),
    ("1.2.1-beta.3", (1, 2, 1), True),
    ("junk", (0, 0, 0), False),
])
def test_parse_version(raw, core, pre):
    assert updater.parse_version(raw) == (core, pre)


def test_extract_version():
    src = '"""doc"""\n\n__version__ = "1.4.0"\nAPP_NAME = "Sentinel"\n'
    assert updater.extract_version(src) == "1.4.0"
    assert updater.extract_version("no version here") is None


# ----------------------------------------------------------- URL handling --

@pytest.mark.parametrize("url,repo", [
    ("https://github.com/seb/sentinel.git", "seb/sentinel"),
    ("https://github.com/seb/sentinel", "seb/sentinel"),
    ("https://github.com/seb/sentinel/", "seb/sentinel"),
    ("git@github.com:seb/sentinel.git", "seb/sentinel"),
    ("https://gitlab.com/seb/sentinel.git", None),
    ("not a url", None),
])
def test_repo_from_url(url, repo):
    assert updater.repo_from_url(url) == repo


def test_pip_install_command():
    cmd = updater.pip_install_command("seb/sentinel")
    assert cmd == "pip install --upgrade git+https://github.com/seb/sentinel.git"


# -------------------------------------------------------- install detection --

def test_install_mode_source_git(tmp_path):
    pkg = tmp_path / "repo" / "sentinel"
    pkg.mkdir(parents=True)
    (tmp_path / "repo" / ".git").mkdir()
    assert updater.install_mode(str(pkg)) == "source-git"


def test_install_mode_pip(tmp_path):
    pkg = tmp_path / "site-packages" / "sentinel"
    pkg.mkdir(parents=True)
    assert updater.install_mode(str(pkg)) == "pip"


def test_install_mode_plain_source(tmp_path):
    pkg = tmp_path / "extracted" / "sentinel"
    pkg.mkdir(parents=True)
    assert updater.install_mode(str(pkg)) == "source"


def test_detect_repo_from_direct_url(tmp_path, monkeypatch):
    # a pip install from git writes direct_url.json next to the package
    pkg = tmp_path / "site-packages" / "sentinel"
    pkg.mkdir(parents=True)
    info = tmp_path / "site-packages" / "sentinel_backup-1.2.1.dist-info"
    info.mkdir()
    (info / "direct_url.json").write_text(
        json.dumps({"url": "git+https://github.com/seb/sentinel.git"}))
    assert updater.detect_repo(str(pkg)) == "seb/sentinel"


def test_detect_repo_falls_back_to_constant(tmp_path, monkeypatch):
    pkg = tmp_path / "extracted" / "sentinel"
    pkg.mkdir(parents=True)
    assert updater.detect_repo(str(pkg)) == updater.GITHUB_REPO


# ------------------------------------------------------------- network I/O --

class _FakeResponse(io.BytesIO):
    """Just enough of the object urlopen() returns."""


def test_fetch_latest_version_parses_remote_init(monkeypatch):
    def fake_urlopen(url, timeout=None):
        assert "raw.githubusercontent.com" in url
        assert url.endswith("/sentinel/__init__.py")
        return _FakeResponse(b'"""doc"""\n__version__ = "9.9.9"\n')
    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    version, error = updater.fetch_latest_version("seb/sentinel")
    assert (version, error) == ("9.9.9", None)


def test_fetch_latest_version_offline_is_friendly(monkeypatch):
    def fake_urlopen(url, timeout=None):
        raise urllib.error.URLError("no route to host")
    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    version, error = updater.fetch_latest_version("seb/sentinel")
    assert version is None
    assert "Could not reach GitHub" in error


def test_check_pipeline(monkeypatch):
    monkeypatch.setattr(updater, "detect_repo", lambda *a: "seb/sentinel")
    monkeypatch.setattr(updater, "install_mode", lambda *a: "pip")
    monkeypatch.setattr(updater, "fetch_latest_version",
                        lambda repo: ("9.9.9", None))
    info = updater.check()
    assert info == {"current": updater.__version__, "latest": "9.9.9",
                    "available": True, "error": None,
                    "mode": "pip", "repo": "seb/sentinel"}


def test_check_pipeline_same_version(monkeypatch):
    monkeypatch.setattr(updater, "detect_repo", lambda *a: "seb/sentinel")
    monkeypatch.setattr(updater, "install_mode", lambda *a: "source-git")
    monkeypatch.setattr(updater, "fetch_latest_version",
                        lambda repo: (updater.__version__, None))
    info = updater.check()
    assert info["available"] is False


def test_pip_command_targets_repo():
    cmd = updater._pip_command("seb/sentinel")
    assert cmd[1:4] == ["-m", "pip", "install"]
    assert cmd[-1] == "git+https://github.com/seb/sentinel.git"


def test_bridge_delivers_from_background_thread(qapp):
    """The daemon-thread bridge must deliver its payload to the GUI thread."""
    import threading
    got = []
    bridge = updater._Bridge()
    bridge.done.connect(got.append)
    t = threading.Thread(target=lambda: bridge.done.emit({"ok": 1}),
                         daemon=True)
    t.start()
    for _ in range(100):                # let the queued call arrive
        qapp.processEvents()
        if got:
            break
    assert got == [{"ok": 1}]


# ------------------------------------------------------------ settings UI --

def test_settings_updates_card(qapp, cfg_dir, tmp_path):
    import sentinel.theme as theme
    from sentinel import config
    from sentinel.ui.main_window import MainWindow
    theme.set_theme(theme.DEFAULT_THEME)

    cfg = config.load()
    cfg.update({"sources": [str(tmp_path)], "destination": str(tmp_path),
                "onboarded": True})
    config.save(cfg)
    win = MainWindow(demo=True)
    win.go_to("settings")
    screen = win.screens["settings"]

    # the card is there and shows the current version
    assert screen.upd_cb.isChecked() is True
    assert f"v{updater.__version__}" in screen.upd_status.text()
    assert screen.update_btn.isHidden()

    # a check that finds a newer pip version reveals the Update button
    fake = {"current": updater.__version__, "latest": "9.9.9",
            "available": True, "error": None, "mode": "pip",
            "repo": "seb/sentinel"}
    screen._updates_checked(fake)
    assert not screen.update_btn.isHidden()
    assert "9.9.9" in screen.upd_status.text()

    # up-to-date feedback
    fake2 = dict(fake, latest=updater.__version__, available=False)
    screen._updates_checked(fake2)
    assert screen.update_btn.isHidden()
    assert "up to date" in screen.upd_status.text()

    # offline feedback stays friendly
    screen._updates_checked(dict(fake, latest=None, available=False,
                                 error="Could not reach GitHub (URLError)."))
    assert "GitHub" in screen.upd_status.text()

    # the startup toggle persists
    screen.upd_cb.setChecked(False)
    assert config.load()["update_check"] is False
    win.close()


def test_version_was_bumped():
    import sentinel
    assert sentinel.__version__ == "1.2.1"
