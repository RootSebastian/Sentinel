"""History & Restore screen.

Left: the log of every backup run (date, status, size, duration) with a
details card for the selected run. Right: restore - one button per backed
up folder for the two-click flow, plus the advanced file picker.

Restore is always non-destructive: it copies files into a folder you
choose and never deletes anything (see restore_engine.py).
"""

import os
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView,
                             QMessageBox, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget, QFrame, QPushButton)

from sentinel import config, history
from sentinel.theme import Pal, icon
from sentinel.ui.restore_dialog import (RestoreDialog,
                                        quick_restore_folder)
from sentinel.widgets import Card, human_bytes, icon_label, label, \
    status_color

#: history status -> color kind used across widgets
STATUS_KIND = {"completed": "ok", "warnings": "warn", "cancelled": "idle",
               "failed": "bad", "running": "accent"}

COLUMNS = ["When", "Status", "Mode", "Files", "Size", "Duration"]


def _fmt_duration(seconds):
    if seconds is None:
        return "—"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


def _clear_layout(layout):
    """Remove everything from a layout, including widgets nested in
    sub-layouts (plain takeAt() would orphan them - and orphaned widgets
    keep painting on top of the parent card)."""
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()
        else:
            child = item.layout()
            if child is not None:
                _clear_layout(child)
                child.deleteLater()


def _fmt_when(iso):
    try:
        dt = datetime.fromisoformat(iso)
        return dt.astimezone().strftime("%a %d %b · %H:%M")
    except (TypeError, ValueError):
        return "—"


class HistoryScreen(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.records = []

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # ---- page header --------------------------------------------------
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(label("History & Restore", size=18, bold=True))
        head.addWidget(label("Every backup run is logged here - and you can "
                             "bring your files back any time.", size=13,
                            color=Pal.DIM))
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(14)

        # ---- left column: run log + details --------------------------------
        left = QVBoxLayout()
        left.setSpacing(14)

        clear_btn = QPushButton("Clear log")
        clear_btn.setObjectName("Ghost")
        clear_btn.setIcon(icon("trash", Pal.FAINT, 14))
        clear_btn.clicked.connect(self._clear_history)
        self.table_card = Card("Backup history", right=clear_btn)
        self.table_card.set_expanding()

        self.empty_lbl = label("No backups yet - your runs will be listed "
                               "here.", size=12, color=Pal.FAINT)
        self.table_card.add(self.empty_lbl)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setShowGrid(False)
        self.table.itemSelectionChanged.connect(self._show_details)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(COLUMNS)):
            header.setSectionResizeMode(col,
                                        QHeaderView.ResizeMode.ResizeToContents)
        self.table_card.add(self.table)

        left.addWidget(self.table_card)

        self.detail_card = Card("Run details")
        self.detail_holder = QVBoxLayout()
        self.detail_holder.setSpacing(6)
        self.detail_card.vbox.addLayout(self.detail_holder)
        left.addWidget(self.detail_card)
        body.addLayout(left, 5)

        # ---- right column: restore -----------------------------------------
        right = QVBoxLayout()
        right.setSpacing(14)

        restore_card = Card("Restore")
        restore_card.set_expanding()
        restore_card.add(label("Copy files from the backup to any folder on "
                               "this computer.", size=12, color=Pal.DIM,
                              wrap=True))
        self.folders_holder = QVBoxLayout()
        self.folders_holder.setSpacing(6)
        restore_card.vbox.addLayout(self.folders_holder)

        self.browse_btn = QPushButton("  Browse & pick files…")
        self.browse_btn.setIcon(icon("search", Pal.DIM, 16))
        self.browse_btn.clicked.connect(self._browse_restore)
        restore_card.add(self.browse_btn)
        right.addWidget(restore_card)

        safety = Card()
        srow = QHBoxLayout()
        srow.setSpacing(10)
        srow.addWidget(icon_label("info", Pal.FAINT, 18))
        stxt = label("Restoring is safe: it only copies files into the "
                     "folder you choose. Nothing is ever deleted - not from "
                     "the backup, not from your computer.", size=11,
                    color=Pal.DIM, wrap=True)
        srow.addWidget(stxt, 1)
        safety.vbox.addLayout(srow)
        right.addWidget(safety)

        body.addLayout(right, 3)
        root.addLayout(body, 1)

        self.refresh()

    # ------------------------------------------------------------- refresh --
    def refresh(self):
        """Reload history + folder list (called after every backup)."""
        self.records = history.load()
        has_runs = bool(self.records)
        self.table.setVisible(has_runs)
        self.empty_lbl.setVisible(not has_runs)
        self._rebuild_table()
        self._rebuild_folders()
        self._show_details()

    def _rebuild_table(self):
        self.table.setRowCount(len(self.records))
        for row, rec in enumerate(self.records):
            status_key = rec.get("status", "failed")
            cells = [
                _fmt_when(rec.get("started")),
                history.STATUS_LABELS.get(status_key, status_key),
                (rec.get("mode") or "—").capitalize(),
                f"{rec['files']:,}" if rec.get("files") else "—",
                human_bytes(rec["bytes"]) if rec.get("bytes") else "—",
                _fmt_duration(rec.get("duration_s")),
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 1:
                    kind = STATUS_KIND.get(status_key, "bad")
                    item.setForeground(QColor(status_color(kind)))
                if col in (3,):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight |
                        Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, col, item)
        if self.records and not self.table.selectionModel().selectedRows():
            self.table.selectRow(0)

    def _rebuild_folders(self):
        _clear_layout(self.folders_holder)

        dest = config.load().get("destination")
        if not dest or not os.path.isdir(os.path.expanduser(dest)):
            if not self.records:
                self.folders_holder.addWidget(
                    label("Run your first backup and restore options will "
                          "appear here.", size=12, color=Pal.FAINT, wrap=True))
                self.browse_btn.setEnabled(False)
                return
            dest = self.records[0].get("dest")
        dest = os.path.expanduser(dest or "")
        if not dest or not os.path.isdir(dest):
            self.folders_holder.addWidget(
                label("The backup destination is not reachable.",
                      size=12, color=Pal.WARNING, wrap=True))
            self.browse_btn.setEnabled(False)
            return

        self.browse_btn.setEnabled(True)
        self._dest = dest
        try:
            entries = sorted(n for n in os.listdir(dest)
                             if os.path.isdir(os.path.join(dest, n)))
        except OSError:
            entries = []
        if not entries:
            self.folders_holder.addWidget(
                label("The backup folder is empty.", size=12,
                      color=Pal.FAINT, wrap=True))
            return
        for name in entries[:8]:
            row = QFrame()
            row.setObjectName("ListItem")
            h = QHBoxLayout(row)
            h.setContentsMargins(10, 6, 8, 6)
            h.setSpacing(8)
            h.addWidget(icon_label("folder", Pal.ACCENT, 16))
            h.addWidget(label(name, size=12), 1)
            btn = QPushButton("Restore")
            btn.clicked.connect(lambda _=False, n=name:
                                self._restore_folder(n))
            h.addWidget(btn)
            self.folders_holder.addWidget(row)
        if len(entries) > 8:
            self.folders_holder.addWidget(
                label(f"…and {len(entries) - 8} more - use Browse & pick "
                      "files.", size=11, color=Pal.FAINT))
        self.folders_holder.addStretch(1)

    # ------------------------------------------------------------- details --
    def _selected_record(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        return self.records[row] if 0 <= row < len(self.records) else None

    def _show_details(self):
        # clear old rows (including widgets nested in the row layouts)
        _clear_layout(self.detail_holder)

        rec = self._selected_record()
        if rec is None:
            self.detail_holder.addWidget(
                label("Select a backup run to see its details.", size=12,
                      color=Pal.FAINT))
            return

        status_key = rec.get("status", "failed")
        kind = STATUS_KIND.get(status_key, "bad")
        head = label(history.STATUS_LABELS.get(status_key, status_key),
                     size=14, bold=True, color=status_color(kind))
        self.detail_holder.addWidget(head)
        self._detail_row("When", _fmt_when(rec.get("started")))
        if rec.get("duration_s") is not None:
            self._detail_row("Took", _fmt_duration(rec.get("duration_s")))
        folders = [os.path.basename(os.path.expanduser(s))
                   for s in rec.get("sources") or []]
        if folders:
            self._detail_row("Folders", ", ".join(folders))
        if rec.get("dest"):
            self._detail_row("Destination", rec["dest"])
        if rec.get("files"):
            self._detail_row("Copied",
                             f"{rec['files']:,} files · "
                             f"{human_bytes(rec.get('bytes') or 0)}")
        if rec.get("message"):
            self._detail_row("Result", rec["message"], wrap=True)

        dest = os.path.expanduser(rec.get("dest") or "")
        btn_row = QHBoxLayout()
        btn = QPushButton("  Restore from this backup…")
        btn.setObjectName("Primary")
        btn.setIcon(icon("restore", Pal.ON_ACCENT, 16))
        btn.setEnabled(bool(dest) and os.path.isdir(dest))
        btn.clicked.connect(lambda: self._open_picker(dest))
        btn_row.addWidget(btn)
        btn_row.addStretch(1)
        self.detail_holder.addLayout(btn_row)

    def _detail_row(self, key, value, wrap=False):
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(label(f"{key}:", size=12, color=Pal.DIM))
        row.addWidget(label(str(value), size=12, wrap=wrap), 1)
        self.detail_holder.addLayout(row)

    # ------------------------------------------------------------- actions --
    def _open_picker(self, dest):
        if dest:
            RestoreDialog(dest, self).exec()

    def _browse_restore(self):
        dest = getattr(self, "_dest", None) or \
            os.path.expanduser(config.load().get("destination") or "")
        if dest and os.path.isdir(dest):
            RestoreDialog(dest, self).exec()

    def _restore_folder(self, name):
        quick_restore_folder(self, getattr(self, "_dest", ""), name)

    def _clear_history(self):
        q = QMessageBox(self)
        q.setWindowTitle("Clear history")
        q.setText("Forget the list of backup runs? The backups themselves "
                  "are not touched.")
        q.setIcon(QMessageBox.Icon.Question)
        q.setStandardButtons(QMessageBox.StandardButton.Yes |
                             QMessageBox.StandardButton.No)
        if q.exec() == QMessageBox.StandardButton.Yes:
            history.clear()
            self.refresh()
