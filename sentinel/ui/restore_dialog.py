"""Restore UI - the advanced file picker and the shared progress panel.

Two entry points:

- ``RestoreDialog``       browse the backup as a checkable file tree and
                          restore whatever you tick (also used for
                          "Restore from this backup" on a history row)
- ``quick_restore_folder``  the two-click flow for one whole folder:
                          pick a target, confirm, restore

Both run the actual copy on a worker thread (``RestoreWorker``) and show
the same live progress panel.
"""

import os

from PyQt6.QtCore import QThread, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFileSystemModel
from PyQt6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog,
                             QHBoxLayout, QLineEdit, QMessageBox,
                             QPlainTextEdit, QProgressBar, QPushButton,
                             QStackedWidget, QTreeView, QVBoxLayout, QWidget)

from sentinel.restore_engine import (RestoreWorker, default_target,
                                     restore_items_from_paths)
from sentinel.theme import Pal, icon, mono_font
from sentinel.widgets import label, icon_label

CHECK_ROLE = int(Qt.ItemDataRole.CheckStateRole)


# ---------------------------------------------------------------------------
# Checkable file tree
# ---------------------------------------------------------------------------
class CheckableFileSystemModel(QFileSystemModel):
    """QFileSystemModel with checkboxes.

    Checking a folder means "everything inside it": children inherit the
    check automatically, and explicit checks below a newly checked folder
    are dropped. Folders that are only partly selected show a dash.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checks = {}                  # absolute path -> Qt.CheckState

    def flags(self, index):
        return super().flags(index) | Qt.ItemFlag.ItemIsUserCheckable

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == CHECK_ROLE and index.isValid():
            return self._state_for(self.filePath(index))
        return super().data(index, role)

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == CHECK_ROLE:
            state = Qt.CheckState(value) if isinstance(value, int) else value
            path = self.filePath(index)
            self._checks[path] = state
            # descendants now inherit this state - drop their own
            prefix = path + os.sep
            for k in [k for k in self._checks if k.startswith(prefix)]:
                del self._checks[k]
            self._emit_subtree(index)
            p = index.parent()
            while p.isValid():
                self.dataChanged.emit(p, p, [CHECK_ROLE])
                p = p.parent()
            return True
        return super().setData(index, value, role)

    # -- state resolution ---------------------------------------------------
    def _state_for(self, path):
        """Check state for `path`: its explicit state, inherited from a
        checked ancestor, or PartiallyChecked when descendants disagree."""
        state = self._checks.get(path)
        if state == Qt.CheckState.Checked:
            if self._has_descendant(path, Qt.CheckState.Unchecked):
                return Qt.CheckState.PartiallyChecked
            return Qt.CheckState.Checked
        if state == Qt.CheckState.Unchecked:
            if self._has_descendant(path, Qt.CheckState.Checked):
                return Qt.CheckState.PartiallyChecked
            return Qt.CheckState.Unchecked
        # no explicit state: inherit from the nearest checked ancestor.
        # The walk is hard-bound: os.path.dirname has fixed points ("/",
        # "//") where it returns its own input and would loop forever.
        cur = path
        for _ in range(128):
            nxt = os.path.dirname(cur)
            if nxt == cur:
                break
            if self._checks.get(nxt) == Qt.CheckState.Checked:
                return Qt.CheckState.Checked      # inherited
            cur = nxt
        if self._has_descendant(path, None):
            return Qt.CheckState.PartiallyChecked
        return Qt.CheckState.Unchecked

    def _has_descendant(self, path, state):
        """True if any explicitly-set state below `path` exists (state=None
        means any state at all)."""
        prefix = path + os.sep
        for k, v in self._checks.items():
            if k != path and k.startswith(prefix):
                if state is None or v == state:
                    return True
        return False

    def _emit_subtree(self, index):
        self.dataChanged.emit(index, index, [CHECK_ROLE])
        for r in range(self.rowCount(index)):
            self._emit_subtree(self.index(r, 0, index))

    def checked_paths(self):
        """Explicitly checked paths with anything nested inside another
        checked path removed (the ancestor already covers it). Note: a
        folder shown as PartiallyChecked still counts as included - the
        dash is a display state meaning "checked, minus a few things"."""
        checked = [p for p, v in self._checks.items()
                   if v == Qt.CheckState.Checked]
        checked.sort(key=lambda p: p.count(os.sep))     # shallowest first
        picked = []
        for p in checked:
            if any(p.startswith(k + os.sep) for k in picked):
                continue
            picked.append(p)
        return picked

    def selection(self):
        """(includes, excludes) for the restore engine.

        `excludes` are the paths the user explicitly unchecked INSIDE a
        checked folder - they are skipped via rsync --exclude. Exclusion
        wins over re-checking something below it (documented, safe)."""
        includes = self.checked_paths()
        excludes = []
        for p, v in self._checks.items():
            if v != Qt.CheckState.Unchecked:
                continue
            if any(p.startswith(i + os.sep) for i in includes):
                excludes.append(p)
        return includes, sorted(excludes)


def describe_selection(paths):
    """(text, n_items) describing what is checked, e.g. '2 folders · 34 files'."""
    dirs = files = 0
    capped = False
    for p in paths:
        if os.path.isdir(p):
            dirs += 1
            for _root, dnames, fnames in os.walk(p):
                dirs += len(dnames)
                files += len(fnames)
                if files + dirs > 20_000:
                    capped = True
                    break
            if capped:
                break
        else:
            files += 1
    if dirs == 0 and files == 0:
        return "Nothing selected yet", 0
    if capped:
        return "More than 20,000 files selected", dirs + files
    parts = []
    if dirs:
        parts.append(f"{dirs} folder{'s' if dirs != 1 else ''}")
    if files:
        parts.append(f"{files:,} file{'s' if files != 1 else ''}")
    return " · ".join(parts), dirs + files


# ---------------------------------------------------------------------------
# Shared progress panel
# ---------------------------------------------------------------------------
class RestoreProgressPanel(QWidget):
    """Runs a RestoreWorker and shows live progress + log.

    Emits ``done(ok, message, target)`` when the restore finishes and
    ``closeRequested()`` when the user presses Close (or closes the
    window after cancelling).
    """

    done = pyqtSignal(bool, str, str)
    closeRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._worker = None
        self._target = ""
        self._close_after = False

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(10)

        self.status_lbl = label("Preparing…", size=13, bold=True)
        self._set_status("accent", "Preparing…")
        vbox.addWidget(self.status_lbl)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        vbox.addWidget(self.progress)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(mono_font(11))
        self.log.setMaximumHeight(170)
        vbox.addWidget(self.log, 1)

        btns = QHBoxLayout()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("Ghost")
        self.cancel_btn.clicked.connect(self._cancel)
        btns.addWidget(self.cancel_btn)
        btns.addStretch(1)
        self.open_btn = QPushButton("  Open folder")
        self.open_btn.setIcon(icon("folder", Pal.DIM, 15))
        self.open_btn.clicked.connect(self._open_target)
        self.open_btn.hide()
        btns.addWidget(self.open_btn)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.closeRequested.emit)
        self.close_btn.hide()
        btns.addWidget(self.close_btn)
        vbox.addLayout(btns)

    # -- lifecycle ----------------------------------------------------------
    def start(self, items, target):
        self._target = target
        self._thread = QThread()
        self._worker = RestoreWorker(items, target)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self.log.appendPlainText)
        self._worker.status.connect(self._status_slot)
        self._worker.progress.connect(self.progress.setValue)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def is_running(self):
        return self._thread is not None and self._thread.isRunning()

    def request_cancel_and_close(self):
        """Cancel the restore; the panel will ask to close when it lands."""
        self._close_after = True
        self._set_status("idle", "Cancelling…")
        self.cancel_btn.setEnabled(False)
        if self._worker:
            self._worker.cancel()

    # -- slots ---------------------------------------------------------------
    def _status_slot(self, text):
        self.status_lbl.setText(text[-120:])

    def _set_status(self, kind, text):
        from sentinel.widgets import status_color
        color = status_color(kind)
        self.status_lbl.setText(
            f'<span style="color:{color}">&#9679;</span>&nbsp;&nbsp;{text}')

    def _cancel(self):
        if self._worker:
            self._set_status("idle", "Cancelling…")
            self.cancel_btn.setEnabled(False)
            self._worker.cancel()

    def _on_finished(self, ok, msg):
        self._set_status("ok" if ok else "bad",
                         "Restore complete" if ok else "Restore failed")
        if ok:
            self.progress.setValue(100)
        self.log.appendPlainText(msg)
        self.cancel_btn.hide()
        self.open_btn.setVisible(ok)
        self.close_btn.show()
        self.done.emit(ok, msg, self._target)
        if self._close_after:
            self.closeRequested.emit()

    def _open_target(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._target))


class RestoreRunDialog(QDialog):
    """Modal dialog hosting a RestoreProgressPanel (used by quick restore)."""

    def __init__(self, items, target, parent=None, title="Restoring files"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(600, 380)
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(18, 18, 18, 18)
        self.panel = RestoreProgressPanel()
        self.panel.closeRequested.connect(self.accept)
        vbox.addWidget(self.panel)
        self.panel.start(items, target)

    def reject(self):
        if self.panel.is_running():
            self.panel.request_cancel_and_close()
            return
        super().reject()


# ---------------------------------------------------------------------------
# Advanced picker
# ---------------------------------------------------------------------------
class RestoreDialog(QDialog):
    """Browse the backup as a checkable tree, pick a target, restore."""

    def __init__(self, dest, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Restore from backup")
        self.resize(780, 560)
        self.dest = os.path.abspath(os.path.expanduser(dest or ""))
        self._target = default_target("picked-files")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        # header
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(icon_label("restore", Pal.ACCENT, 26))
        txt = QVBoxLayout()
        txt.setSpacing(1)
        txt.addWidget(label("Restore files from your backup", size=15,
                            bold=True))
        txt.addWidget(label(self.dest, size=11, color=Pal.DIM, mono=True,
                            wrap=True))
        head.addLayout(txt, 1)
        root.addLayout(head)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        available = os.path.isdir(self.dest) and bool(os.listdir(self.dest))
        self.stack.addWidget(self._build_picker() if available
                             else self._build_unavailable())
        self.progress_panel = RestoreProgressPanel()
        self.progress_panel.closeRequested.connect(self.accept)
        self.stack.addWidget(self.progress_panel)

    # -- pages ---------------------------------------------------------------
    def _build_unavailable(self):
        page = QWidget()
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(0, 8, 0, 8)
        vbox.setSpacing(8)
        vbox.addWidget(icon_label("info", Pal.WARNING, 24))
        vbox.addWidget(label("This backup location is empty or not reachable:",
                             size=13, bold=True))
        vbox.addWidget(label(self.dest, size=11, color=Pal.DIM, mono=True,
                             wrap=True))
        vbox.addWidget(label("Connect the drive or pick another backup from "
                             "the history list.", size=12, color=Pal.DIM,
                             wrap=True))
        vbox.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        vbox.addWidget(close)
        return page

    def _build_picker(self):
        page = QWidget()
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(10)

        vbox.addWidget(label("Tick the folders and files you want back:",
                             size=12, color=Pal.DIM))

        self.model = CheckableFileSystemModel(self)
        self.model.setRootPath(self.dest)
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(self.dest))
        for col in range(2, self.model.columnCount()):
            self.tree.hideColumn(col)
        self.tree.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(
            0, self.tree.header().ResizeMode.Stretch)
        vbox.addWidget(self.tree, 1)

        self.summary_lbl = label("Nothing selected yet", size=12,
                                 color=Pal.DIM)
        vbox.addWidget(self.summary_lbl)

        # target row
        trow = QHBoxLayout()
        trow.setSpacing(8)
        trow.addWidget(label("Restore to:", size=12))
        self.target_edit = QLineEdit(self._target)
        self.target_edit.setReadOnly(True)
        trow.addWidget(self.target_edit, 1)
        choose = QPushButton("Choose…")
        choose.clicked.connect(self._choose_target)
        trow.addWidget(choose)
        vbox.addLayout(trow)

        # buttons
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        self.restore_btn = QPushButton("  Restore")
        self.restore_btn.setObjectName("Primary")
        self.restore_btn.setIcon(icon("restore", Pal.ON_ACCENT, 16))
        self.restore_btn.setEnabled(False)
        self.restore_btn.clicked.connect(self.accept)
        btns.addWidget(self.restore_btn)
        vbox.addLayout(btns)

        self.model.dataChanged.connect(self._refresh_summary)
        return page

    # -- actions -------------------------------------------------------------
    def _refresh_summary(self, *_args):
        paths = self.model.checked_paths()
        text, n = describe_selection(paths)
        self.summary_lbl.setText(text)
        self.restore_btn.setEnabled(n > 0)
        self.restore_btn.setText(f"  Restore {n} item{'s' if n != 1 else ''}"
                                 if n else "  Restore")

    def _choose_target(self):
        dlg = QFileDialog(self, "Choose where to restore")
        dlg.setFileMode(QFileDialog.FileMode.Directory)
        dlg.setOption(QFileDialog.Option.ShowDirsOnly, True)
        dlg.selectFile(self._target)
        if dlg.exec() and dlg.selectedFiles():
            self._target = dlg.selectedFiles()[0]
            self.target_edit.setText(self._target)

    def accept(self):
        if self.stack.currentWidget() is self.progress_panel:
            super().accept()          # progress page: let Close handle it
            return
        includes, excludes = self.model.selection()
        items = restore_items_from_paths(self.dest, includes, excludes)
        if not items:
            return
        target = self._target
        if os.path.isdir(target) and os.listdir(target):
            q = QMessageBox(self)
            q.setWindowTitle("Folder is not empty")
            q.setText(f"“{target}” already contains files. Restoring may "
                      "overwrite files with the same names. Continue?")
            q.setIcon(QMessageBox.Icon.Warning)
            q.setStandardButtons(QMessageBox.StandardButton.Yes |
                                 QMessageBox.StandardButton.No)
            if q.exec() != QMessageBox.StandardButton.Yes:
                return
        self.stack.setCurrentWidget(self.progress_panel)
        self.progress_panel.start(items, target)

    def reject(self):
        if self.stack.currentWidget() is self.progress_panel \
                and self.progress_panel.is_running():
            self.progress_panel.request_cancel_and_close()
            return
        super().reject()


# ---------------------------------------------------------------------------
# Quick folder flow
# ---------------------------------------------------------------------------
def quick_restore_folder(parent, backup_root, folder_name):
    """Two-click restore of one whole folder: pick target, confirm, go."""
    src = os.path.join(backup_root, folder_name)
    if not os.path.isdir(src):
        QMessageBox.information(parent, "Nothing to restore",
                                f"“{folder_name}” was not found in the "
                                "backup.")
        return

    dlg = QFileDialog(parent, f"Restore “{folder_name}” to…")
    dlg.setFileMode(QFileDialog.FileMode.Directory)
    dlg.setOption(QFileDialog.Option.ShowDirsOnly, True)
    dlg.selectFile(default_target(folder_name))
    if not dlg.exec() or not dlg.selectedFiles():
        return
    target = dlg.selectedFiles()[0]

    if os.path.isdir(target) and os.listdir(target):
        q = QMessageBox(parent)
        q.setWindowTitle("Folder is not empty")
        q.setText(f"“{target}” already contains files. Restoring may "
                  "overwrite files with the same names. Continue?")
        q.setIcon(QMessageBox.Icon.Warning)
        q.setStandardButtons(QMessageBox.StandardButton.Yes |
                             QMessageBox.StandardButton.No)
        if q.exec() != QMessageBox.StandardButton.Yes:
            return

    dlg = RestoreRunDialog([(src, folder_name)], target, parent,
                           title=f"Restoring {folder_name}")
    dlg.exec()
