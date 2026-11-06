"""First-run setup wizard: pick folders -> pick destination -> pick schedule.

Four friendly pages with step dots, validation, and plain-language guidance.
"""

import os
import shutil

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QFrame,
                             QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                             QPushButton, QScrollArea, QStackedWidget,
                             QVBoxLayout, QWidget)

from sentinel import config
from sentinel.theme import Pal, icon
from sentinel.widgets import (Card, OptionCard, label, icon_label, hline,
                     human_bytes)

COMMON_FOLDERS = ["Documents", "Pictures", "Videos", "Music",
                  "Desktop", "Downloads", "Projects"]


class Page(QWidget):
    """One wizard page: a centered column of content."""

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 24, 36, 24)
        self.col = QVBoxLayout()
        self.col.setSpacing(12)
        outer.addLayout(self.col)
        outer.addStretch(1)


class FirstRunWizard(QDialog):
    """Runs once on first launch; writes config and sets onboarded=True."""

    accepted_setup = pyqtSignal()

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.chosen = set()           # source folders picked on page 2
        self.setWindowTitle("Welcome to Sentinel")
        self.setFixedSize(700, 580)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self._build_welcome()
        self._build_what()
        self._build_where()
        self._build_when()

        # footer: step dots + back/next
        footer = QWidget()
        frow = QHBoxLayout(footer)
        frow.setContentsMargins(36, 14, 36, 20)
        self.dots = [label("\u25cf", size=11, color=Pal.BORDER) for _ in range(4)]
        self.dots[0].setText(f'<span style="color:{Pal.ACCENT}">&#9679;</span>')
        box = QHBoxLayout()
        box.setSpacing(6)
        for d in self.dots:
            box.addWidget(d)
        frow.addLayout(box)
        frow.addStretch(1)
        self.back_btn = QPushButton("Back")
        self.back_btn.clicked.connect(self.prev)
        self.next_btn = QPushButton("Next")
        self.next_btn.setObjectName("Primary")
        self.next_btn.clicked.connect(self.next)
        frow.addWidget(self.back_btn)
        frow.addWidget(self.next_btn)
        root.addWidget(hline())
        root.addWidget(footer)

        self._sync_footer()

    # ------------------------------------------------------------- pages --
    def _build_welcome(self):
        pg = Page()
        pg.col.addSpacing(48)
        pg.col.addWidget(icon_label("shield", Pal.ACCENT, 64), 0,
                         Qt.AlignmentFlag.AlignHCenter)
        pg.col.addSpacing(8)
        t = label("Welcome to Sentinel", size=24, bold=True)
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pg.col.addWidget(t)
        sub = label("Automatic backups and a friendly system monitor,\n"
                    "in one app. Setup takes about a minute.",
                    size=14, color=Pal.DIM, wrap=True)
        sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        pg.col.addWidget(sub)
        pg.col.addSpacing(14)
        for line in ("Automatic backups on a schedule you choose",
                     "Restore-ready copies of every folder you pick",
                     "Live CPU, memory, network and disk - like Task Manager"):
            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(icon_label("check", Pal.SUCCESS, 16))
            row.addWidget(label(line, size=13))
            row.addStretch(1)
            wrap = QWidget()
            wrap.setLayout(row)
            pg.col.addWidget(wrap)
        self.stack.addWidget(pg)

    def _build_what(self):
        pg = Page()
        pg.col.addWidget(label("What should we back up?", size=18, bold=True))
        pg.col.addWidget(label("Pick the folders that matter. You can add "
                               "more later.", size=13, color=Pal.DIM))
        pg.col.addSpacing(4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        v = QVBoxLayout(holder)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.what_checks = []
        home = os.path.expanduser("~")
        for name in COMMON_FOLDERS:
            path = os.path.join(home, name)
            if os.path.isdir(path):
                cb = QCheckBox(f"~/{name}")
                cb.setProperty("path", path)
                cb.toggled.connect(lambda _: self._sync_footer())
                v.addWidget(cb)
                self.what_checks.append(cb)
        add_btn = QPushButton("+  Add another folder…")
        add_btn.setObjectName("Ghost")
        add_btn.clicked.connect(self._add_folder)
        v.addWidget(add_btn)
        v.addStretch(1)
        scroll.setWidget(holder)
        pg.col.addWidget(scroll, 1)
        self.stack.addWidget(pg)

    def _build_where(self):
        pg = Page()
        pg.col.addWidget(label("Where should backups live?", size=18, bold=True))
        pg.col.addWidget(label("A copy of your folders is stored here.",
                               size=13, color=Pal.DIM))
        pg.col.addSpacing(4)

        tip = Card()
        tip.vbox.setSpacing(4)
        tip.vbox.addWidget(label("Good to know", size=12, bold=True))
        tip.vbox.addWidget(label(
            "Best: an external drive or a second internal disk.\n"
            "Okay: another partition.\n"
            "Avoid: the same folder as the originals - if the disk dies, "
            "both copies die.", size=12, color=Pal.DIM, wrap=True))
        pg.col.addWidget(tip)

        pick = Card()
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(icon_label("drive", Pal.ACCENT, 20))
        self.where_lbl = label("No destination chosen yet", size=13,
                               color=Pal.WARNING)
        row.addWidget(self.where_lbl)
        row.addStretch(1)
        browse = QPushButton("Choose…")
        browse.clicked.connect(self._browse_dest)
        row.addWidget(browse)
        pick.vbox.addLayout(row)
        self.where_free = label("", size=12, color=Pal.FAINT)
        pick.vbox.addWidget(self.where_free)
        pg.col.addWidget(pick)
        pg.col.addStretch(1)
        self.stack.addWidget(pg)

    def _build_when(self):
        pg = Page()
        pg.col.addWidget(label("How often should Sentinel back up?", size=18,
                               bold=True))
        pg.col.addWidget(label("You can always run a backup manually, any "
                               "time.", size=13, color=Pal.DIM))
        pg.col.addSpacing(4)

        self.when_manual = OptionCard("Only when I click",
                                      "No automatic backups. You start every "
                                      "run yourself.")
        self.when_daily = OptionCard("Every day",
                                     "Runs once a day while Sentinel is open "
                                     "or the system scheduler is enabled.",
                                     badge="Recommended")
        self.when_weekly = OptionCard("Every week",
                                      "Runs once a week - good for large "
                                      "folders that change slowly.")
        self.when_daily.set_checked(True)
        pg.col.addWidget(self.when_manual)
        pg.col.addWidget(self.when_daily)
        pg.col.addWidget(self.when_weekly)

        row = QHBoxLayout()
        row.addWidget(label("Run at (HH:MM):", size=13))
        self.time_edit = QLineEdit("03:00")
        self.time_edit.setFixedWidth(90)
        row.addWidget(self.time_edit)
        row.addStretch(1)
        pg.col.addLayout(row)
        pg.col.addStretch(1)
        self.stack.addWidget(pg)

    # ------------------------------------------------------------- actions --
    def _add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Choose a folder to back up")
        if not path:
            return
        if path in self.chosen:
            return
        self.chosen.add(path)
        for cb in self.what_checks:
            if cb.property("path") == path:
                return
        # add a checkbox for the custom folder, checked
        cb = QCheckBox(path)
        cb.setProperty("path", path)
        cb.setChecked(True)
        cb.toggled.connect(lambda _: self._sync_footer())
        holder = self.what_checks[0].parentWidget() if self.what_checks else None
        if holder is not None:
            lay = holder.layout()
            lay.insertWidget(lay.count() - 2, cb)   # before add-button + stretch
        self.what_checks.append(cb)
        self._sync_footer()

    def _browse_dest(self):
        path = QFileDialog.getExistingDirectory(self, "Choose backup destination")
        if not path:
            return
        self.cfg["destination"] = path
        self.where_lbl.setText(path)
        self.where_lbl.setStyleSheet(f"color: {Pal.TEXT}; background: transparent;")
        try:
            u = shutil.disk_usage(path)
            self.where_free.setText(
                f"{human_bytes(u.free)} free of {human_bytes(u.total)}")
        except OSError:
            self.where_free.setText("")
        self._sync_footer()

    # ------------------------------------------------------------- nav --
    def goto(self, i):
        i = max(0, min(3, i))
        self.stack.setCurrentIndex(i)
        self._sync_footer()

    def next(self):
        i = self.stack.currentIndex()
        if i == 1 and not self._chosen_paths():
            QMessageBox.warning(self, "Pick at least one folder",
                                "Choose at least one folder to back up, "
                                "or go back.")
            return
        if i == 2 and not self.cfg.get("destination"):
            QMessageBox.warning(self, "Choose a destination",
                                "Pick where the backups should be stored.")
            return
        if i == 3:
            self._finish()
            return
        self.goto(i + 1)

    def prev(self):
        self.goto(self.stack.currentIndex() - 1)

    def _sync_footer(self):
        i = self.stack.currentIndex()
        self.back_btn.setVisible(i > 0)
        self.next_btn.setText("Start using Sentinel" if i == 3 else "Next")
        # don't let users continue past an invalid page - the button simply
        # stays disabled until the page has what it needs
        if i == 1:
            self.next_btn.setEnabled(bool(self._chosen_paths()))
        elif i == 2:
            self.next_btn.setEnabled(bool(self.cfg.get("destination")))
        else:
            self.next_btn.setEnabled(True)
        for j, d in enumerate(self.dots):
            color = Pal.ACCENT if j == i else Pal.BORDER
            d.setText(f'<span style="color:{color}">&#9679;</span>')

    def _chosen_paths(self):
        return [cb.property("path") for cb in self.what_checks if cb.isChecked()]

    def _finish(self):
        self.cfg["sources"] = self._chosen_paths()
        if self.when_manual.is_checked():
            self.cfg["schedule"] = "manual"
        elif self.when_weekly.is_checked():
            self.cfg["schedule"] = "weekly"
        else:
            self.cfg["schedule"] = "daily"
        self.cfg["schedule_time"] = self.time_edit.text().strip() or "03:00"
        self.cfg["mode"] = "incremental"
        self.cfg["onboarded"] = True
        config.save(self.cfg)
        self.accepted_setup.emit()
        self.accept()
