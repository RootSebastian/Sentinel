"""Settings screen - appearance (theme gallery), notifications and about.

The theme gallery applies themes live: clicking a card rebuilds the whole
UI with the new palette instantly - no restart, no extra clicks.
"""

import os

from PyQt6 import sip
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QCheckBox, QFrame, QGridLayout, QHBoxLayout,
                             QPushButton, QVBoxLayout, QWidget)

from sentinel import __version__, config, theme
from sentinel.theme import THEMES, Pal, icon, mix
from sentinel.widgets import Card, icon_label, label


def _dot(color: str, size: int = 15) -> QFrame:
    """A small round color swatch with a ring that keeps it readable on
    both plain and accent-tinted card backgrounds."""
    d = QFrame()
    d.setFixedSize(size, size)
    d.setCursor(Qt.CursorShape.PointingHandCursor)
    d.setStyleSheet(
        f"background: {color}; border-radius: {size // 2};"
        f"border: 1px solid {mix(Pal.BORDER, Pal.TEXT, 0.15)};")
    return d


class ThemeCard(QFrame):
    """One clickable theme preview: name, dark/light tag and color swatches."""

    def __init__(self, t: theme.Theme, win):
        super().__init__()
        self.t = t
        self.win = win
        self.setObjectName("OptionCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("selected", t.key == theme.active().key)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)

        txt = QVBoxLayout()
        txt.setSpacing(1)
        txt.addWidget(label(t.name, size=13, bold=True))
        txt.addWidget(label("Dark" if t.dark else "Light", size=11,
                            color=Pal.DIM))
        row.addLayout(txt, 1)

        # a mini-palette on a subtle plate: the theme's accent + chart colors.
        # the plate keeps the dots readable even on the selected (tinted) card.
        plate = QFrame()
        plate.setStyleSheet(
            f"background: {Pal.FIELD}; border-radius: 9px; border: none;")
        ph = QHBoxLayout(plate)
        ph.setContentsMargins(8, 5, 8, 5)
        ph.setSpacing(5)
        for c in (t.accent, t.cpu, t.mem, t.up):
            ph.addWidget(_dot(c))
        row.addWidget(plate)

        # check mark on the active theme (theme text color - always reads
        # clearly on the accent-tinted selected card)
        self.check = icon_label("check", Pal.TEXT, 16)
        self.check.setVisible(t.key == theme.active().key)
        row.addWidget(self.check)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # set_theme() rebuilds the whole UI and destroys this card, so
            # the switch must NOT run inside this event handler - defer it
            # to the next event-loop turn (same pattern as the sidebar's
            # theme menu). Switching synchronously here used to crash with
            # "wrapped C/C++ object of type ThemeCard has been deleted".
            win, key = self.win, self.t.key
            QTimer.singleShot(0, lambda: win.set_theme(key))
        # the deferred switch cannot have run yet, but stay safe anyway:
        # never touch the C++ side of a widget that may have been deleted
        if not sip.isdeleted(self):
            super().mousePressEvent(event)


class SettingsScreen(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cfg = win.cfg

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # ---- page header --------------------------------------------------
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(label("Settings", size=18, bold=True))
        head.addWidget(label("Make Sentinel look and behave the way you want.",
                             size=13, color=Pal.DIM))
        root.addLayout(head)

        # ---- appearance ----------------------------------------------------
        appearance = Card("Appearance")
        appearance.add(label("Pick a theme - it applies instantly and is "
                             "remembered for next time.", size=12,
                            color=Pal.DIM))
        grid = QGridLayout()
        grid.setSpacing(10)
        for i, t in enumerate(THEMES.values()):
            grid.addWidget(ThemeCard(t, win), i // 4, i % 4)
        for col in range(4):
            grid.setColumnStretch(col, 1)
        appearance.add(grid)
        appearance.add(label("Tip: the Theme button in the sidebar switches "
                             "without leaving this page, and Ctrl+, opens "
                             "Settings from anywhere.", size=11,
                            color=Pal.FAINT, wrap=True))
        root.addWidget(appearance)

        # ---- notifications -------------------------------------------------
        notif = Card("Notifications")
        self.notif_cb = QCheckBox(
            "Show a desktop notification when a backup finishes or fails")
        self.notif_cb.setChecked(self.cfg.get("notifications", True))
        self.notif_cb.toggled.connect(self._save_notifications)
        notif.add(self.notif_cb)
        notif.add(label("Notifications appear through the system tray.",
                        size=11, color=Pal.FAINT))
        root.addWidget(notif)

        # ---- about ---------------------------------------------------------
        about = Card("About")
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(icon_label("shield", Pal.ACCENT, 28))
        txt = QVBoxLayout()
        txt.setSpacing(1)
        txt.addWidget(label(f"Sentinel  ·  v{__version__}", size=13, bold=True))
        txt.addWidget(label("Automatic backups and a friendly system monitor "
                            "for Linux.", size=12, color=Pal.DIM, wrap=True))
        row.addLayout(txt, 1)
        about.add(row)

        cfg_row = QHBoxLayout()
        cfg_row.setSpacing(8)
        cfg_row.addWidget(label("Settings are stored in:", size=12,
                                color=Pal.DIM))
        path = label(config.CONFIG_DIR, size=12, mono=True, color=Pal.TEXT)
        cfg_row.addWidget(path, 1)
        open_btn = QPushButton("Open folder")
        open_btn.setIcon(icon("folder", Pal.DIM, 15))
        open_btn.clicked.connect(self._open_config_dir)
        cfg_row.addWidget(open_btn)
        about.add(cfg_row)
        root.addWidget(about)

        root.addStretch(1)

    # ------------------------------------------------------------- actions --
    def _save_notifications(self, checked):
        cfg = config.load()
        cfg["notifications"] = bool(checked)
        config.save(cfg)
        self.cfg = cfg

    def _open_config_dir(self):
        os.makedirs(config.CONFIG_DIR, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(config.CONFIG_DIR))
