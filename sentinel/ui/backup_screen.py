"""Backup screen - configure sources, destination, mode and schedule,
then run backups with live progress. Settings auto-save on every change.
"""

import os
import shutil
from datetime import datetime, timedelta, timezone

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QComboBox, QFileDialog, QFrame, QHBoxLayout,
                             QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                             QProgressBar, QPushButton, QSizePolicy,
                             QVBoxLayout, QWidget)

from sentinel import config
from sentinel.theme import Pal, icon, mono_font
from sentinel.widgets import (Card, OptionCard, dot_label, human_bytes,
                              icon_label, label)

MODES = [
    ("incremental", "Incremental", "Copies new and changed files. Fast, and "
     "nothing gets deleted from the backup.", "Recommended"),
    ("mirror", "Mirror", "The backup becomes an exact copy. Files you delete "
     "at home are deleted from the backup too.", None),
    ("full", "Full copy", "Re-copies everything, every time. Slowest, most "
     "thorough.", None),
]

SCHEDULES = [("manual", "Only when I click"),
             ("hourly", "Every hour"),
             ("daily", "Every day"),
             ("weekly", "Every week")]


class BackupScreen(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cfg = win.cfg
        self._building = True

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # ---------- top row: sources + destination/schedule -------------
        top = QHBoxLayout()
        top.setSpacing(14)

        # sources card
        add_btn = QPushButton("+  Add folder")
        add_btn.clicked.connect(self._add_source)
        self.sources_card = Card("Folders to back up", right=add_btn)
        self.sources_card.set_expanding()
        self.sources_holder = QVBoxLayout()
        self.sources_holder.setSpacing(6)
        self.sources_card.vbox.addLayout(self.sources_holder)
        top.addWidget(self.sources_card, 1)

        # settings card
        self.settings_card = Card("Destination & schedule")
        self.settings_card.set_expanding()
        self._build_dest_row()
        self._build_mode_row()
        self._build_schedule_row()
        top.addWidget(self.settings_card, 1)
        root.addLayout(top)

        # ---------- activity card ----------------------------------------
        self.activity = Card("Activity")
        status_row = QHBoxLayout()
        self.status_lbl = dot_label("Idle", Pal.DIM, bold=True)
        status_row.addWidget(self.status_lbl)
        status_row.addStretch(1)
        self.pct_lbl = label("", size=12, color=Pal.DIM)
        status_row.addWidget(self.pct_lbl)
        self.activity.vbox.addLayout(status_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.activity.add(self.progress)

        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("  Back up now")
        self.run_btn.setObjectName("Primary")
        self.run_btn.setIcon(icon("play", Pal.ON_ACCENT, 16))
        self.run_btn.clicked.connect(self._start)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("Ghost")
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.hide()
        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.cancel_btn)

        self.details_btn = QPushButton("\u25b8  Technical details")
        self.details_btn.setObjectName("Ghost")
        self.details_btn.setCheckable(True)
        self.details_btn.clicked.connect(self._toggle_details)
        btn_row.addStretch(1)
        btn_row.addWidget(self.details_btn)
        self.activity.vbox.addLayout(btn_row)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(mono_font(11))
        self.log.setVisible(False)
        self.log.setMaximumHeight(170)
        self.activity.add(self.log)
        root.addWidget(self.activity)

        root.addStretch(1)

        # ---------- wiring -------------------------------------------------
        m = win.manager
        m.started.connect(self._on_started)
        m.log.connect(self._append_log)
        m.status.connect(lambda s: self.status_lbl.setText(s[-70:]))
        m.progress.connect(self._on_progress)
        m.finished.connect(self._on_finished)
        if m.is_running():            # theme switched mid-backup: stay truthful
            self._on_started()

        self._rebuild_sources()
        self._building = False

        # in-app scheduler (works while the app is open)
        self.sched_timer = QTimer(self)
        self.sched_timer.timeout.connect(self._check_schedule)
        self.sched_timer.start(30_000)

    # =====================================================================
    # settings UI
    # =====================================================================
    def _build_dest_row(self):
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(icon_label("drive", Pal.ACCENT, 18))
        self.dest_lbl = label("Not set", size=13, color=Pal.WARNING)
        row.addWidget(self.dest_lbl, 1)
        change = QPushButton("Change")
        change.clicked.connect(self._browse_dest)
        row.addWidget(change)
        self.settings_card.vbox.addLayout(row)
        self.dest_free = label("", size=11, color=Pal.FAINT)
        self.settings_card.vbox.addWidget(self.dest_free)

    def _build_mode_row(self):
        self.settings_card.vbox.addWidget(label("Backup mode", size=12,
                                                color=Pal.DIM))
        self.mode_cards = []
        for key, title, desc, badge in MODES:
            card = OptionCard(title, desc, badge=badge)
            card.toggled.connect(lambda checked, k=key: self._set_mode(k, checked))
            self.settings_card.vbox.addWidget(card)
            self.mode_cards.append((key, card))
        self.settings_card.add_stretch(1)

    def _build_schedule_row(self):
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(label("Schedule:", size=13))
        self.sched_combo = QComboBox()
        for key, text in SCHEDULES:
            self.sched_combo.addItem(text, key)
        self.sched_combo.currentIndexChanged.connect(self._save)
        row.addWidget(self.sched_combo)
        self.time_edit = QLineEdit("03:00")
        self.time_edit.setFixedWidth(80)
        self.time_edit.editingFinished.connect(self._save)
        row.addWidget(self.time_edit)
        row.addStretch(1)
        self.settings_card.vbox.addLayout(row)
        hint = label("Applies while Sentinel is open. For 24/7 backups, also "
                     "enable the systemd timer (see run instructions).",
                     size=11, color=Pal.FAINT, wrap=True)
        self.settings_card.vbox.addWidget(hint)

    def _rebuild_sources(self):
        while self.sources_holder.count():
            item = self.sources_holder.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        sources = self.cfg.get("sources") or []
        if not sources:
            empty = label("No folders yet - add the ones you want to keep safe.",
                          size=12, color=Pal.FAINT, wrap=True)
            self.sources_holder.addWidget(empty)
            return
        for path in sources:
            row = QFrame()
            row.setObjectName("ListItem")
            h = QHBoxLayout(row)
            h.setContentsMargins(10, 6, 8, 6)
            h.setSpacing(8)
            h.addWidget(icon_label("folder", Pal.ACCENT, 16))
            h.addWidget(label(path, size=12), 1)
            rm = QPushButton()
            rm.setObjectName("IconButton")
            rm.setIcon(icon("trash", Pal.FAINT, 15))
            rm.clicked.connect(lambda _=False, p=path: self._remove_source(p))
            h.addWidget(rm)
            self.sources_holder.addWidget(row)
        self.sources_holder.addStretch(1)

    # =====================================================================
    # settings changes (auto-save)
    # =====================================================================
    def _add_source(self):
        path = QFileDialog.getExistingDirectory(self, "Choose a folder to back up")
        if not path:
            return
        if path not in self.cfg["sources"]:
            self.cfg["sources"].append(path)
            self._save()
        self._rebuild_sources()

    def _remove_source(self, path):
        if path in self.cfg["sources"]:
            self.cfg["sources"].remove(path)
            self._save()
        self._rebuild_sources()

    def _browse_dest(self):
        path = QFileDialog.getExistingDirectory(self, "Choose backup destination")
        if not path:
            return
        self.cfg["destination"] = path
        self._save()
        self._refresh_dest()

    def _set_mode(self, key, checked):
        if not checked or self._building:
            return
        if key != self.cfg["mode"]:
            if key == "mirror":
                confirm = QMessageBox(self)
                confirm.setWindowTitle("Mirror mode")
                confirm.setText("Mirror mode deletes files from the backup "
                                "when you delete them at home.\nUse it only "
                                "if you want an exact copy. Continue?")
                confirm.setIcon(QMessageBox.Icon.Warning)
                confirm.setStandardButtons(QMessageBox.StandardButton.Yes |
                                           QMessageBox.StandardButton.No)
                if confirm.exec() != QMessageBox.StandardButton.Yes:
                    self._select_mode(self.cfg["mode"])
                    return
            self.cfg["mode"] = key
            self._save()

    def _select_mode(self, key):
        for k, card in self.mode_cards:
            card.set_checked(k == key)

    def _save(self):
        if self._building:
            return
        self.cfg["schedule"] = self.sched_combo.currentData() or "manual"
        self.cfg["schedule_time"] = self.time_edit.text().strip() or "03:00"
        config.save(self.cfg)
        self._refresh_dest()

    def _refresh_dest(self):
        dest = self.cfg.get("destination")
        if dest and os.path.isdir(os.path.expanduser(dest)):
            self.dest_lbl.setText(dest)
            self.dest_lbl.setStyleSheet(
                f"color: {Pal.TEXT}; background: transparent;")
            try:
                u = shutil.disk_usage(os.path.expanduser(dest))
                self.dest_free.setText(
                    f"{human_bytes(u.free)} free of {human_bytes(u.total)}")
            except OSError:
                self.dest_free.setText("")
        else:
            self.dest_lbl.setText("Not set")
            self.dest_lbl.setStyleSheet(
                f"color: {Pal.WARNING}; background: transparent;")
            self.dest_free.setText("")

    def refresh_from_config(self):
        """Called when config changes elsewhere (wizard finished)."""
        self.cfg = config.load()
        for i in range(self.sched_combo.count()):
            if self.sched_combo.itemData(i) == self.cfg.get("schedule"):
                self.sched_combo.setCurrentIndex(i)
        self.time_edit.setText(self.cfg.get("schedule_time", "03:00"))
        self._select_mode(self.cfg.get("mode", "incremental"))
        self._rebuild_sources()
        self._refresh_dest()

    # =====================================================================
    # running backups
    # =====================================================================
    def _start(self):
        self.win.manager.start()

    def _cancel(self):
        self.win.manager.cancel()

    def _toggle_details(self, checked):
        self.log.setVisible(checked)
        self.details_btn.setText("\u25be  Technical details" if checked
                                 else "\u25b8  Technical details")

    def _on_started(self):
        self.run_btn.hide()
        self.cancel_btn.show()
        self.progress.setValue(0)
        self.pct_lbl.setText("0%")
        self.status_lbl.setText('<span style="color:'
                                f'{Pal.ACCENT}">&#9679;</span>&nbsp;&nbsp;Starting…')
        self.log.appendPlainText(
            f"=== Backup started {datetime.now():%Y-%m-%d %H:%M:%S} ===")

    def _append_log(self, text):
        self.log.appendPlainText(text)

    def _on_progress(self, pct):
        self.progress.setValue(pct)
        self.pct_lbl.setText(f"{pct}%")

    def _on_finished(self, ok, msg):
        self.run_btn.show()
        self.cancel_btn.hide()
        if ok:
            self.progress.setValue(100)
            self.pct_lbl.setText("Done")
            self.status_lbl.setText(f'<span style="color:'
                                    f'{Pal.SUCCESS}">&#9679;</span>&nbsp;&nbsp;'
                                    'Backup complete')
        else:
            self.pct_lbl.setText("")
            self.status_lbl.setText(f'<span style="color:'
                                    f'{Pal.DANGER}">&#9679;</span>&nbsp;&nbsp;'
                                    'Backup failed - see details')
        self.log.appendPlainText(msg)

    # =====================================================================
    # in-app scheduler
    # =====================================================================
    def _check_schedule(self):
        if self.win.manager.is_running():
            return
        cfg = config.load()
        if not cfg.get("sources") or not cfg.get("destination"):
            return
        schedule = cfg.get("schedule", "manual")
        if schedule == "manual":
            return
        now = datetime.now().astimezone()       # timezone-aware local time
        last = cfg.get("last_backup")
        if last:
            last = datetime.fromisoformat(last)
            if last.tzinfo is None:            # legacy configs stored naive UTC
                last = last.replace(tzinfo=timezone.utc)
            last = last.astimezone()           # to local, comparable with now
        else:
            last = None
        try:
            hh, mm = (int(x) for x in cfg.get("schedule_time", "03:00").split(":"))
        except ValueError:
            return
        if schedule == "hourly":
            due = last is None or now - last >= timedelta(hours=1)
        else:
            every = timedelta(days=1 if schedule == "daily" else 7)
            due = (last is None or now - last >= every) and \
                  (now.hour, now.minute) >= (hh, mm)
        if due:
            self.win.manager.start()
