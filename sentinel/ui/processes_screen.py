"""Processes - a friendly Task Manager: live table, search, colored
resource usage, and an "End task" button with confirmation.
"""

import time

import psutil
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView,
                             QLineEdit, QMessageBox, QPushButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout,
                             QWidget)

from sentinel.theme import Pal, icon
from sentinel.widgets import Card, label

# role / alignment constants as ints - avoids per-refresh enum conversion
ROLE_DISPLAY = int(Qt.ItemDataRole.DisplayRole)
ALIGN_RIGHT_V = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class TaskManagerScreen(QWidget):
    COLUMNS = ["PID", "Name", "CPU %", "Memory %", "Status"]
    NUMERIC = {0, 2, 3}

    def __init__(self, win):
        super().__init__()
        self.win = win
        self._filter = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # ---- toolbar -----------------------------------------------------
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.cpu_chip = _chip("CPU")
        self.mem_chip = _chip("Memory")
        self.proc_chip = _chip("Processes")
        bar.addWidget(self.cpu_chip)
        bar.addWidget(self.mem_chip)
        bar.addWidget(self.proc_chip)
        bar.addStretch(1)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search processes…")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(240)
        self.search.addAction(icon("search", Pal.FAINT, 15),
                              QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._set_filter)
        bar.addWidget(self.search)

        self.kill_btn = QPushButton("End task")
        self.kill_btn.setObjectName("Danger")
        self.kill_btn.setEnabled(False)
        self.kill_btn.clicked.connect(self._kill_selected)
        bar.addWidget(self.kill_btn)
        root.addLayout(bar)

        # ---- table --------------------------------------------------------
        card = Card()
        card.set_expanding()
        card.vbox.setContentsMargins(8, 6, 8, 8)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSortIndicator(2, Qt.SortOrder.DescendingOrder)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(True)
        self.table.itemSelectionChanged.connect(
            lambda: self.kill_btn.setEnabled(
                self.table.currentRow() >= 0))
        card.add(self.table)
        root.addWidget(card, 1)

        # ---- wiring --------------------------------------------------------
        psutil.cpu_percent(percpu=True)          # prime counters
        self.refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(2000)

    # ------------------------------------------------------------------ ui --
    def _set_filter(self, text):
        self._filter = text.strip().lower()
        self.refresh()

    def refresh(self):
        sort_col = self.table.horizontalHeader().sortIndicatorSection()
        sort_order = self.table.horizontalHeader().sortIndicatorOrder()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)

        infos = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent",
                                      "memory_percent", "status"]):
            try:
                infos.append(p.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied,
                    psutil.ZombieProcess):
                continue

        for info in infos:
            name = (info["name"] or "?")
            if self._filter and (self._filter not in name.lower()
                                 and self._filter not in str(info["pid"])):
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [info["pid"], name, info["cpu_percent"] or 0.0,
                      info["memory_percent"] or 0.0, info["status"] or ""]
            for col, val in enumerate(values):
                item = QTableWidgetItem()
                if col in self.NUMERIC:
                    item.setData(ROLE_DISPLAY,
                                 int(val) if col == 0 else round(float(val), 1))
                    item.setTextAlignment(ALIGN_RIGHT_V)
                else:
                    item.setData(ROLE_DISPLAY, str(val))
                if col in (2, 3):           # color-code CPU / RAM hogs
                    hot = (col == 2 and val >= 50) or (col == 3 and val >= 40)
                    crit = (col == 2 and val >= 90) or (col == 3 and val >= 85)
                    if crit:
                        item.setForeground(QBrush(QColor(Pal.DANGER)))
                    elif hot:
                        item.setForeground(QBrush(QColor(Pal.WARNING)))
                self.table.setItem(row, col, item)

        self.table.sortItems(sort_col, sort_order)
        self.table.setSortingEnabled(True)

        self.cpu_chip.set_value(f"{psutil.cpu_percent():.0f}%")
        self.mem_chip.set_value(f"{psutil.virtual_memory().percent:.0f}%")
        self.proc_chip.set_value(f"{len(infos)}")

    # --------------------------------------------------------------- kill --
    def _kill_selected(self):
        row = self.table.currentRow()
        if row < 0:
            return
        pid = self.table.item(row, 0).data(ROLE_DISPLAY)
        name = self.table.item(row, 1).text()
        confirm = QMessageBox(self)
        confirm.setWindowTitle("End task")
        confirm.setText(f"End <b>{name}</b> (PID {pid})?\n"
                        "Unsaved work in this program will be lost.")
        confirm.setIcon(QMessageBox.Icon.Warning)
        confirm.setStandardButtons(QMessageBox.StandardButton.EndTask |
                                   QMessageBox.StandardButton.Cancel)
        confirm.button(QMessageBox.StandardButton.EndTask).setObjectName("Danger")
        if confirm.exec() != QMessageBox.StandardButton.EndTask:
            return
        try:
            psutil.Process(int(pid)).terminate()
            self.refresh()
        except psutil.NoSuchProcess:
            self.refresh()
        except psutil.AccessDenied:
            QMessageBox.warning(self, "Permission denied",
                                "That process belongs to root or another "
                                "user - you cannot end it without elevated "
                                "privileges.")


class _chip(QWidget):
    """Small stat chip for the toolbar."""

    def __init__(self, title):
        super().__init__()
        self.setObjectName("Card")
        self.setFixedHeight(44)
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 8, 14, 8)
        h.setSpacing(8)
        self.title_lbl = label(title, size=11, color=Pal.DIM)
        self.value_lbl = label("—", size=14, bold=True)
        h.addWidget(self.title_lbl)
        h.addWidget(self.value_lbl)

    def set_value(self, text):
        self.value_lbl.setText(text)
