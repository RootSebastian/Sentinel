"""In-app updates from GitHub.

Sentinel is typically installed from a GitHub repository, either as a
git clone / editable install or via ``pip install git+https://…``. This
module lets the app answer two questions for the user:

    1. "Is there a newer version?"  - fetch ``sentinel/__init__.py`` from
       the repository's default branch and compare ``__version__``.
    2. "Can you install it?"        - yes for pip installs (one click);
       git checkouts are told to ``git pull`` instead.

The check never blocks the interface and never complains when offline.

Where the repository lives is auto-detected: the git remote when running
from a checkout, the ``direct_url.json`` pip wrote for git installs, and
a hardcoded fallback (``GITHUB_REPO``) as the last resort.
"""

import glob
import json
import os
import re
import subprocess
import sys
import threading
import urllib.request

from PyQt6 import sip
from PyQt6.QtCore import QObject, QProcess, Qt, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QDialog, QHBoxLayout,
                             QMessageBox, QPlainTextEdit, QPushButton,
                             QVBoxLayout)

from sentinel import __version__
from sentinel.theme import Pal, mono_font
from sentinel.widgets import label

# Fallback when the origin cannot be auto-detected (used when running
# from an extracted zip rather than a clone or a pip install).
GITHUB_REPO = "RootSebastian/sentinel"

CHECK_TIMEOUT = 6  # seconds; the check stays silent on failure anyway


# --------------------------------------------------------------------------
# Pure helpers - unit tested, no network, no Qt.
# --------------------------------------------------------------------------

def parse_version(v):
    """'v1.2.1-beta' -> ((1, 2, 1), True). Non-numeric parts count as 0."""
    v = str(v).strip().lstrip("vV")
    core = re.split(r"[-+]", v, 1)[0]
    parts = []
    for piece in core.split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3]), bool(re.search(r"-\w", v))


def is_newer(remote, local):
    """True when ``remote`` is strictly newer than ``local``."""
    (r_core, r_pre), (l_core, l_pre) = parse_version(remote), parse_version(local)
    if r_core != l_core:
        return r_core > l_core
    # same numbers: a final release beats a pre-release ("1.2.1" > "1.2.1-beta")
    return l_pre and not r_pre


def extract_version(text):
    """Pull ``__version__ = "…"`` out of Python source text."""
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.M)
    return m.group(1) if m else None


def repo_from_url(url):
    """'git@github.com:OWN/REPO.git' or 'https://github.com/OWN/REPO(.git)'
    -> 'OWN/REPO'; None for anything that is not a GitHub URL."""
    m = re.search(
        r"github\.com[/:]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$",
        str(url).strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def repo_root(pkg_dir=None):
    """Folder that contains the ``sentinel`` package (repo or site-packages)."""
    d = pkg_dir or os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(d.rstrip("/"))


def install_mode(pkg_dir=None):
    """How Sentinel is running on this machine.

    'source-git' - a git clone (or editable install): update with git pull
    'pip'        - installed into site-packages: update with one click
    'source'     - extracted zip / loose files: no safe self-update
    """
    root = repo_root(pkg_dir)
    if os.path.isdir(os.path.join(root, ".git")):
        return "source-git"
    if os.path.basename(root) == "site-packages" or "site-packages" in root:
        return "pip"
    return "source"


def _git_origin_url(root):
    """`git remote get-url origin` for the checkout at ``root`` (or None)."""
    try:
        out = subprocess.run(
            ["git", "remote", "get-url", "origin"], cwd=root,
            capture_output=True, text=True, timeout=5).stdout
        return out.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _direct_url(pkg_dir=None):
    """The git URL pip recorded when installing from git, if any."""
    root = repo_root(pkg_dir)
    for path in glob.glob(os.path.join(root, "sentinel_backup-*.dist-info",
                                       "direct_url.json")):
        try:
            with open(path) as f:
                return json.load(f).get("url")
        except (OSError, ValueError):
            return None
    return None


def detect_repo(pkg_dir=None):
    """Best guess at 'OWNER/REPO' on GitHub for this installation."""
    root = repo_root(pkg_dir)
    if os.path.isdir(os.path.join(root, ".git")):
        repo = repo_from_url(_git_origin_url(root) or "")
        if repo:
            return repo
    repo = repo_from_url(_direct_url(pkg_dir) or "")
    if repo:
        return repo
    return GITHUB_REPO


def pip_install_command(repo):
    return f"pip install --upgrade git+https://github.com/{repo}.git"


def git_pull_command(pkg_dir=None):
    return f"cd {repo_root(pkg_dir)} && git pull"


# --------------------------------------------------------------------------
# Network check (blocking - call via start_check / startup_check).
# --------------------------------------------------------------------------

def fetch_latest_version(repo):
    """(version, None) on success or (None, friendly_error)."""
    url = f"https://raw.githubusercontent.com/{repo}/HEAD/sentinel/__init__.py"
    try:
        with urllib.request.urlopen(url, timeout=CHECK_TIMEOUT) as r:
            text = r.read().decode("utf-8", "replace")
    except OSError as e:                     # URLError, timeout, DNS, ...
        return None, f"Could not reach GitHub ({e.__class__.__name__})."
    version = extract_version(text)
    if not version:
        return None, "Could not read the version from the repository."
    return version, None


def check():
    """Everything the UI needs to decide what to offer. Blocking."""
    repo = detect_repo()
    latest, error = fetch_latest_version(repo)
    return {
        "current": __version__,
        "latest": latest,
        "available": bool(latest and is_newer(latest, __version__)),
        "error": error,
        "mode": install_mode(),
        "repo": repo,
    }


# --------------------------------------------------------------------------
# Background plumbing. Plain daemon threads + a Qt signal bridge: daemon
# threads never crash the app on exit the way a mid-run QThread can.
# --------------------------------------------------------------------------

_REFS = []  # keep bridges alive until they have delivered their signal


class _Bridge(QObject):
    done = pyqtSignal(dict)          # check result


class _UpdateBridge(QObject):
    line = pyqtSignal(str)           # pip output
    done = pyqtSignal(bool, str)     # success, message


def start_check(slot):
    """Run :func:`check` in the background; call ``slot(info)`` on the GUI
    thread. ``slot`` should be a bound method of a QWidget so the
    connection is dropped automatically if the widget is destroyed."""
    bridge = _Bridge()
    bridge.done.connect(slot)
    _REFS.append(bridge)

    def work():
        info = check()
        bridge.done.emit(info)
        try:
            _REFS.remove(bridge)
        except ValueError:
            pass

    threading.Thread(target=work, daemon=True).start()
    return bridge


def _pip_command(repo):
    return [sys.executable, "-m", "pip", "install", "--upgrade",
            "--disable-pip-version-check",
            f"git+https://github.com/{repo}.git"]


def start_update(repo, on_line, on_done):
    """ pip install --upgrade git+…  in the background.

    Streams each output line to ``on_line(str)`` and finishes with
    ``on_done(ok, message)`` - both delivered on the GUI thread.
    """
    bridge = _UpdateBridge()
    bridge.line.connect(on_line)
    bridge.done.connect(on_done)
    _REFS.append(bridge)

    def work():
        try:
            proc = subprocess.Popen(
                _pip_command(repo), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in proc.stdout:
                bridge.line.emit(line.rstrip())
            rc = proc.wait()
            ok = rc == 0
            msg = "Update installed." if ok else f"pip exited with code {rc}."
        except OSError as e:
            ok, msg = False, f"Could not run pip: {e}"
        bridge.done.emit(ok, msg)
        try:
            _REFS.remove(bridge)
        except ValueError:
            pass

    threading.Thread(target=work, daemon=True).start()
    return bridge


def restart_app():
    """Start a fresh Sentinel process and leave this one."""
    QProcess.startDetached(sys.executable, ["-m", "sentinel"], os.getcwd())
    QApplication.quit()


# --------------------------------------------------------------------------
# Dialogs and flows used by both the Settings screen and the startup check.
# --------------------------------------------------------------------------

class UpdatePanel(QDialog):
    """Log viewer shown while pip downloads and installs the new version."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Updating Sentinel")
        self.resize(540, 320)
        box = QVBoxLayout(self)
        box.setSpacing(10)
        self.status = label("Downloading and installing the new version…",
                            size=13, wrap=True)
        box.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(mono_font(11))
        self.log.setStyleSheet(
            f"background: {Pal.FIELD}; color: {Pal.TEXT}; border: none;")
        box.addWidget(self.log, 1)
        self.close_btn = QPushButton("Close")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.hide)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.close_btn)
        box.addLayout(row)

    def append(self, line):
        if not sip.isdeleted(self.log):
            self.log.appendPlainText(line)

    def finish(self, ok, message):
        if sip.isdeleted(self):
            return
        self.close_btn.setEnabled(True)
        if ok:
            self.status.setText(
                "Update installed - restart Sentinel to use the new version.")
            self.log.appendPlainText("")
            self.log.appendPlainText("-" * 46)
            self.log.appendPlainText("Update installed successfully.")
            restart = QMessageBox.question(
                self, "Restart Sentinel",
                "The new version is installed.\nRestart Sentinel now to "
                "use it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if restart is QMessageBox.StandardButton.Yes:
                restart_app()
        else:
            self.status.setText(f"Update failed - {message}")
            self.log.appendPlainText("")
            self.log.appendPlainText(f"FAILED: {message}")


def begin_update(parent, repo):
    """Open the progress panel and start pip. Returns the panel."""
    panel = UpdatePanel(parent)
    panel.show()
    start_update(repo, panel.append, panel.finish)
    return panel


class _ManualDialog(QDialog):
    """Tells source installs how to update; the command is selectable."""

    def __init__(self, parent, info):
        super().__init__(parent)
        self.setWindowTitle("Update available")
        self.resize(500, 210)
        box = QVBoxLayout(self)
        box.setSpacing(10)
        box.addWidget(label(f"Version v{info['latest']} is available "
                            f"(you have v{info['current']}).",
                            size=13, bold=True, wrap=True))
        if info["mode"] == "source-git":
            box.addWidget(label("You are running from a git checkout - "
                                "update it with:", size=12, wrap=True))
            command = git_pull_command()
        else:
            box.addWidget(label("You are running from an extracted copy. "
                                "Easiest fix - install from GitHub once, "
                                "then future updates are one click:",
                                size=12, wrap=True))
            command = pip_install_command(info["repo"])
        self.cmd = label(command, size=12, mono=True)
        self.cmd.setTextInteractionFlags(
            self.cmd.textInteractionFlags()
            | Qt.TextInteractionFlag.TextSelectableByMouse)
        self.cmd.setStyleSheet(
            f"background: {Pal.FIELD}; color: {Pal.TEXT}; "
            "border-radius: 6px; padding: 8px;")
        box.addWidget(self.cmd)
        row = QHBoxLayout()
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.clicked.connect(self._copy)
        ok_btn = QPushButton("Close")
        ok_btn.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(self.copy_btn)
        row.addWidget(ok_btn)
        box.addLayout(row)

    def _copy(self):
        QApplication.clipboard().setText(self.cmd.text())


def show_manual_update_dialog(parent, info):
    if not sip.isdeleted(parent):
        _ManualDialog(parent, info).exec()


def _announce_update(parent, info):
    """Startup path: a quiet question, only when there is something new."""
    if sip.isdeleted(parent):
        return
    if info["mode"] == "pip":
        answer = QMessageBox.question(
            parent, "Sentinel update available",
            f"A new version (v{info['latest']}) is available - you have "
            f"v{info['current']}.\n\nUpdate Sentinel now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer is QMessageBox.StandardButton.Yes:
            begin_update(parent, info["repo"])
    else:
        show_manual_update_dialog(parent, info)


def startup_check(win):
    """Check shortly after launch; stay completely silent unless a newer
    version exists (and silent forever when offline).  ``handle`` closes
    over ``win``, which lives for the whole session, so the connection can
    never outlive its receiver."""
    def handle(info):
        if not info.get("error") and info.get("available"):
            _announce_update(win, info)

    start_check(handle)
