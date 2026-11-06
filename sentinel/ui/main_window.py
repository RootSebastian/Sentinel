"""Main window: sidebar navigation shell, shared BackupManager (one
worker thread for the whole app), live theme switching and optional system
tray integration.
"""

import os
from datetime import datetime, timezone

from PyQt6.QtCore import (QEvent, Qt, QObject, QRectF, QTimer, QThread,
                         pyqtSignal)
from PyQt6.QtGui import QAction, QColor, QCursor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow,
                             QMessageBox, QPushButton, QStackedWidget,
                             QSystemTrayIcon, QVBoxLayout, QWidget)

from sentinel import __version__, config, theme
from sentinel.backup_engine import BackupWorker
from sentinel import history
from sentinel.theme import Pal, icon
from sentinel.widgets import label, dot_label


# ---------------------------------------------------------------------------
# Backup manager - single owner of the backup worker thread
# ---------------------------------------------------------------------------
class BackupManager(QObject):
    started = pyqtSignal()
    log = pyqtSignal(str)
    status = pyqtSignal(str)
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)

    def __init__(self, parent_win):
        super().__init__(parent_win)
        self.win = parent_win
        self.thread = None
        self.worker = None
        self._hist_id = None

    def is_running(self):
        return self.thread is not None and self.thread.isRunning()

    def start(self):
        if self.is_running():
            return
        cfg = config.load()
        sources, dest = cfg.get("sources") or [], cfg.get("destination")
        if not sources or not dest:
            QMessageBox.information(
                self.win, "Almost there",
                "Pick at least one folder and a backup destination first "
                "(Backup screen).")
            self.win.go_to("backup")
            return

        dest_abs = os.path.abspath(os.path.expanduser(dest))
        for s in sources:
            src_abs = os.path.abspath(os.path.expanduser(s))
            if dest_abs == src_abs or dest_abs.startswith(src_abs + os.sep):
                QMessageBox.warning(
                    self.win, "Bad destination",
                    "The destination is inside a source folder - the backup "
                    "would grow forever. Pick another location.")
                self.win.go_to("backup")
                return
        if cfg.get("mode") == "mirror":
            q = QMessageBox(self.win)
            q.setWindowTitle("Mirror mode")
            q.setText("Mirror mode deletes files from the backup when you "
                      "delete them at home. Continue?")
            q.setIcon(QMessageBox.Icon.Warning)
            q.setStandardButtons(QMessageBox.StandardButton.Yes |
                                 QMessageBox.StandardButton.No)
            if q.exec() != QMessageBox.StandardButton.Yes:
                return

        self._hist_id = history.begin(cfg)   # logged even if it fails
        self.thread = QThread()
        self.worker = BackupWorker(sources, dest, cfg.get("mode", "incremental"))
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self.log)
        self.worker.status.connect(self.status)
        self.worker.progress.connect(self.progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._on_thread_done)
        self.thread.start()
        self.started.emit()

    def cancel(self):
        if self.worker:
            self.worker.cancel()

    def _on_finished(self, ok, msg):
        cfg = config.load()
        if ok:
            cfg["last_backup"] = datetime.now(timezone.utc).isoformat()
            config.save(cfg)
        # classify the run for the history log
        if self.worker is not None and self.worker._cancelled:
            status = "cancelled"
        elif ok:
            status = "warnings" if "warning" in msg.lower() else "completed"
        else:
            status = "failed"
        if self._hist_id:
            stats = self.worker.last_stats if self.worker else {}
            history.complete(self._hist_id, status, stats=stats, message=msg)
            self._hist_id = None
        self.finished.emit(ok, msg)

    def _on_thread_done(self):
        self.thread = None
        self.worker = None


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
def _swatch_icon(color: str) -> QIcon:
    """A small filled circle in `color` - used in the theme quick-switcher."""
    pm = QPixmap(18, 18)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QRectF(3, 3, 12, 12))
    p.end()
    return QIcon(pm)


class Sidebar(QWidget):
    navigated = pyqtSignal(str)

    ITEMS = [
        ("dashboard", "Dashboard", "dashboard"),
        ("backup", "Backup", "backup"),
        ("history", "History", "clock"),
        ("processes", "Processes", "processes"),
        ("monitor", "System Monitor", "monitor"),
        ("settings", "Settings", "settings"),
    ]

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setFixedWidth(212)
        self._buttons = {}

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(14, 18, 14, 14)
        vbox.setSpacing(6)

        # logo
        logo = QHBoxLayout()
        logo.setSpacing(9)
        from sentinel.widgets import icon_label
        logo.addWidget(icon_label("shield", Pal.ACCENT, 22))
        name = label("Sentinel", size=15, bold=True)
        logo.addWidget(name)
        logo.addStretch(1)
        vbox.addLayout(logo)
        vbox.addSpacing(14)

        for key, title, icon_name in self.ITEMS:
            btn = QPushButton(f"  {title}")
            btn.setObjectName("NavBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setIcon(icon(icon_name, Pal.DIM, 20))
            btn.clicked.connect(lambda _=False, k=key: self.select(k))
            vbox.addWidget(btn)
            self._buttons[key] = btn

        vbox.addStretch(1)

        # quick theme switcher (full gallery lives in Settings)
        self.theme_btn = QPushButton("  Theme")
        self.theme_btn.setObjectName("NavBtn")
        self.theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_btn.setIcon(icon("palette", Pal.DIM, 18))
        self.theme_btn.clicked.connect(self._show_theme_menu)
        vbox.addWidget(self.theme_btn)

        # footer status
        vbox.addSpacing(4)
        self.status_lbl = dot_label("Ready", Pal.DIM, size=12)
        vbox.addWidget(self.status_lbl)
        vbox.addWidget(label(f"v{__version__}", size=11, color=Pal.FAINT))

        self.select("dashboard")

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(Pal.SIDEBAR))
        # subtle separator on the sidebar's right edge
        p.fillRect(self.width() - 1, 0, 1, self.height(),
                   QColor(theme.mix(Pal.BORDER, Pal.SIDEBAR, 0.45)))
        p.end()

    def select(self, key, emit=True):
        """Update nav button states. Emits `navigated` only when the user
        clicked (not when go_to calls us back - that would recurse)."""
        items = {item[0]: item for item in self.ITEMS}
        for k, btn in self._buttons.items():
            checked = (k == key)
            btn.setChecked(checked)
            item = items.get(k)
            color = Pal.ACCENT if checked else Pal.DIM
            btn.setIcon(icon(item[2], color, 20))
        self.current = key
        if emit:
            self.navigated.emit(key)

    def set_backup_running(self, running):
        if running:
            self.status_lbl.setText(f'<span style="color:'
                                    f'{Pal.ACCENT}">&#9679;</span>&nbsp;&nbsp;'
                                    'Backing up…')
        else:
            self.status_lbl.setText(f'<span style="color:'
                                    f'{Pal.SUCCESS}">&#9679;</span>&nbsp;&nbsp;'
                                    'Ready')

    # ------------------------------------------------------------------ themes
    def _show_theme_menu(self):
        """Compact theme picker: every theme with its accent color dot.

        The actual switch is deferred with a zero-timer so the menu (and its
        nested event loop) is fully closed before the UI is rebuilt.
        """
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        for key, t in theme.THEMES.items():
            act = menu.addAction(t.name)
            act.setIcon(_swatch_icon(t.accent))
            act.setToolTip("Dark theme" if t.dark else "Light theme")
            if key == theme.active().key:
                font = act.font()
                font.setBold(True)
                act.setFont(font)
            act.triggered.connect(lambda _=False, k=key: self._pick_theme(k))
        menu.exec(QCursor.pos())

    def _pick_theme(self, key):
        def switch():
            # guard: this sidebar may already have been replaced
            if self.win.sidebar is self:
                self.win.set_theme(key)
        QTimer.singleShot(0, switch)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, demo=False):
        super().__init__()
        self.demo = demo
        self.cfg = config.load()
        self.manager = BackupManager(self)
        self.screens = {}
        self.sidebar = None
        self._current_key = "dashboard"

        self.setWindowTitle("Sentinel — Backups & System Monitor")
        self.setWindowIcon(icon("shield", Pal.ACCENT, 64))
        self.resize(1220, 780)
        self.setMinimumSize(1020, 680)

        self._build_shell()

        # keyboard shortcuts: Ctrl+1..6 switch screens, Ctrl+, opens Settings
        keys = ("dashboard", "backup", "history", "processes", "monitor",
                "settings")
        for i, key in enumerate(keys, 1):
            sc = QAction(self)
            sc.setShortcut(f"Ctrl+{i}")
            sc.triggered.connect(lambda _=False, k=key: self.go_to(k))
            self.addAction(sc)
        sc = QAction(self)
        sc.setShortcut("Ctrl+,")
        sc.triggered.connect(lambda _=False: self.go_to("settings"))
        self.addAction(sc)

        # manager wiring - connected ONCE, to slots on this window (which
        # survives retheming), never to screens or sidebars directly
        self.manager.started.connect(self._on_manager_started)
        self.manager.finished.connect(self._on_manager_finished)

        # system tray (skip in demo/screenshot mode)
        self.tray = None
        if not demo:
            self._setup_tray()

        # first-run wizard
        if not demo and not self.cfg.get("onboarded"):
            QTimer.singleShot(150, self.open_wizard)

    # ------------------------------------------------------------------ shell
    def _build_shell(self):
        """(Re)build the sidebar + screen stack. Called once at startup and
        again on every theme switch, so every widget is created with colors
        from the active theme."""
        shell = QHBoxLayout()
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        self.sidebar = Sidebar(self)
        self.sidebar.navigated.connect(self.go_to)
        shell.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        from sentinel.ui.dashboard import DashboardScreen
        from sentinel.ui.backup_screen import BackupScreen
        from sentinel.ui.history_screen import HistoryScreen
        from sentinel.ui.processes_screen import TaskManagerScreen
        from sentinel.ui.monitor_screen import MonitorScreen
        from sentinel.ui.settings_screen import SettingsScreen
        self.screens = {
            "dashboard": DashboardScreen(self),
            "backup": BackupScreen(self),
            "history": HistoryScreen(self),
            "processes": TaskManagerScreen(self),
            "monitor": MonitorScreen(self),
            "settings": SettingsScreen(self),
        }
        for key in ("dashboard", "backup", "history", "processes", "monitor",
                    "settings"):
            self.stack.addWidget(self.screens[key])
        shell.addWidget(self.stack, 1)

        central = QWidget()
        central.setLayout(shell)

        old = self.takeCentralWidget()     # never auto-deleted by Qt
        self.setCentralWidget(central)
        if old is not None:
            old.deleteLater()
            # processEvents() skips DeferredDelete events, so process them
            # explicitly - otherwise the old screens (and their QTimers!)
            # would linger as zombies after every theme switch.
            # Scoped to `old`: only the old shell's pending delete is
            # flushed, never unrelated deleteLater() calls elsewhere.
            # NOTE: this destroys the old widget tree *immediately*, so
            # set_theme() must never be called from inside an event handler
            # of a widget in that tree (its super().xxxEvent() would then
            # run on a deleted object). Callers inside the old UI must
            # defer with QTimer.singleShot(0, ...) - see ThemeCard and
            # Sidebar._pick_theme.
            QApplication.sendPostedEvents(old, QEvent.Type.DeferredDelete)

    # ------------------------------------------------------------------ nav --
    def go_to(self, key):
        if key in self.screens:
            self._current_key = key
            self.stack.setCurrentWidget(self.screens[key])
            self.sidebar.select(key, emit=False)   # avoid signal recursion

    def open_wizard(self):
        from sentinel.ui.wizard import FirstRunWizard
        wiz = FirstRunWizard(config.load(), self)
        if wiz.exec():
            self.cfg = config.load()
            self.screens["backup"].refresh_from_config()

    # ---------------------------------------------------------------- themes
    def set_theme(self, key):
        """Switch the whole app to another theme - instantly, no restart.

        Rebuilds the sidebar and every screen, destroying the old widget
        tree immediately. Must therefore NOT be called from inside an event
        handler of a widget in the current UI (e.g. a ThemeCard click) -
        such callers defer via QTimer.singleShot(0, ...) so their handler
        finishes before the old tree is destroyed.
        """
        if key not in theme.THEMES or key == theme.active().key:
            return
        self.cfg = config.load()
        self.cfg["theme"] = key
        config.save(self.cfg)
        theme.set_theme(key, app=QApplication.instance(), save_cfg=False)
        self._build_shell()
        self.go_to(self._current_key)
        self.setWindowIcon(icon("shield", Pal.ACCENT, 64))
        if self.tray:
            self.tray.setIcon(icon("shield", Pal.ACCENT, 48))

    # ----------------------------------------------------------------- tray --
    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(icon("shield", Pal.ACCENT, 48), self)
        from PyQt6.QtWidgets import QMenu
        m = QMenu()
        m.addAction("Open Sentinel", self._show_window)
        m.addAction("Back up now", self.manager.start)
        m.addSeparator()
        m.addAction("Quit", QApplication.instance().quit)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(
            lambda reason: self._show_window()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show()

    def _show_window(self):
        self.showNormal()
        self.activateWindow()

    def _on_manager_started(self):
        self.sidebar.set_backup_running(True)

    def _on_manager_finished(self, ok, msg):
        self.sidebar.set_backup_running(False)
        self._notify_result(ok, msg)
        if "history" in self.screens:
            self.screens["history"].refresh()

    def _notify_result(self, ok, msg):
        cfg = config.load()
        if self.tray and cfg.get("notifications", True):
            title = "Backup complete" if ok else "Backup failed"
            icon_kind = (QSystemTrayIcon.MessageIcon.Information if ok
                         else QSystemTrayIcon.MessageIcon.Critical)
            self.tray.showMessage(title, msg, icon_kind, 4000)

    def closeEvent(self, event):
        if self.tray and not self.demo:
            event.ignore()
            self.hide()
            self.tray.showMessage(
                "Sentinel keeps running",
                "Sentinel is still in the system tray, keeping an eye on "
                "backups. Right-click the tray icon to quit.",
                QSystemTrayIcon.MessageIcon.Information, 3000)
        else:
            event.accept()
