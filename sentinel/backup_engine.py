"""rsync-powered backup engine (incremental / mirror / full).

The engine is UI-agnostic: `run_rsync` is a plain blocking function, and
`BackupWorker` wraps it so the GUI can run it on a QThread without
freezing. The headless `--backup-now` mode uses the same code, so GUI and
scheduled backups behave identically.

`restore_engine.py` reuses the low-level output pump (`_pump`) to bring
files back from a backup.
"""

import os
import re
import shutil
import subprocess

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

RSYNC = shutil.which("rsync")

# fields harvested from rsync's --stats block (used by the history log)
_STATS_PATTERNS = {
    "files": re.compile(r"Number of regular files transferred: ([\d,]+)"),
    "bytes": re.compile(r"Total transferred file size: ([\d,]+) bytes"),
}


def _pump(proc, log, status, progress, should_cancel, stats):
    """Feed rsync output to the callbacks and harvest --stats numbers.

    rsync refreshes its live progress line with \\r, so output must be read
    as raw bytes and split on both \\r and \\n. Returns True if the process
    was cancelled (and therefore terminated).
    """
    def handle(raw):
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            return
        if "%" in line:                    # live progress line from rsync
            m = re.search(r"(\d+)%", line)
            if m:
                progress(int(m.group(1)))
            status(line)
        else:
            for key, rx in _STATS_PATTERNS.items():
                m = rx.search(line)
                if m:
                    stats[key] = int(m.group(1).replace(",", ""))
            log(line)

    pending = b""
    fd = proc.stdout.fileno()
    while True:
        chunk = os.read(fd, 4096)
        if not chunk:
            break
        if should_cancel():
            proc.terminate()
            log("Cancelled by user.")
            return True
        pending += chunk.replace(b"\r", b"\n")
        *lines, pending = pending.split(b"\n")
        for raw in lines:
            handle(raw)
    if pending:
        handle(pending)
    return False


def run_rsync(sources, dest, mode,
              log=print, status=lambda _s: None, progress=lambda _p: None,
              should_cancel=lambda: False):
    """Run one backup job (blocking).

    Returns (success, message, stats) where stats is a dict with `files`
    and `bytes` transferred (harvested from rsync's --stats output).
    """
    if RSYNC is None:
        return False, "rsync not found - install it (e.g. sudo apt install rsync)", {}
    if not sources:
        return False, "No source folders configured.", {}

    dest = os.path.expanduser(dest)
    os.makedirs(dest, exist_ok=True)

    args = [RSYNC, "-a", "--info=progress2", "--stats"]
    if mode == "mirror":
        args.append("--delete")            # dest becomes an exact copy
    elif mode == "full":
        args += ["-W", "--ignore-times"]   # force re-copy of everything
    args += [os.path.expanduser(s) for s in sources]
    args.append(dest + "/")                # each source folder lands inside dest

    log(f"$ {' '.join(args)}")
    proc = subprocess.Popen(args, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, bufsize=0)

    stats = {}
    cancelled = _pump(proc, log, status, progress, should_cancel, stats)
    rc = proc.wait()

    if cancelled:
        return False, "Backup cancelled.", stats
    if rc == 0:
        return True, "Backup completed successfully.", stats
    if rc in (23, 24):
        return True, (f"Completed with warnings (rsync code {rc}: "
                      "some files vanished or could not be read)."), stats
    return False, f"Backup failed (rsync exit code {rc}).", stats


class BackupWorker(QObject):
    """Runs run_rsync in a QThread so the GUI never freezes."""

    log = pyqtSignal(str)
    status = pyqtSignal(str)
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)

    def __init__(self, sources, dest, mode):
        super().__init__()
        self.sources, self.dest, self.mode = sources, dest, mode
        self._cancelled = False
        self.last_stats = {}

    def cancel(self):
        self._cancelled = True

    @pyqtSlot()
    def run(self):
        ok, msg, stats = run_rsync(
            self.sources, self.dest, self.mode,
            log=self.log.emit, status=self.status.emit,
            progress=self.progress.emit,
            should_cancel=lambda: self._cancelled,
        )
        self.last_stats = stats
        self.finished.emit(ok, msg)
