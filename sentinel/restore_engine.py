"""Bring files back from a backup destination (reverse rsync).

Restore is deliberately conservative: `--delete` is never used, so
restoring can only create or overwrite files at the target - it can never
delete anything, neither from the backup nor from the target folder. The
UI additionally suggests a fresh `~/Sentinel restored/...` folder and asks
before writing into a non-empty one.

Each restore item is a (source_path, relative_target) pair; one rsync runs
per item so folders and individual files can be mixed freely.
"""

import os
import subprocess
from datetime import datetime

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from sentinel.backup_engine import RSYNC, _pump


def default_target(base_name="restore"):
    """A fresh, non-destructive default restore folder, e.g.
    ~/Sentinel restored/Documents-20260131-1425"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = (base_name or "restore").strip().replace(os.sep, "-") or "restore"
    return os.path.join(os.path.expanduser("~"), "Sentinel restored",
                        f"{safe}-{stamp}")


def restore_items_from_paths(root, paths, excluded=()):
    """Build the restore item list for checked `paths` inside `root`.

    Items are (source, relative target, excludes) triples; `excludes` are
    paths the user unchecked inside a checked folder and are skipped with
    rsync --exclude. Checking the root itself means "everything" and
    expands to its top-level entries. Anything nested inside another
    checked path is dropped - the ancestor already covers it."""
    root = os.path.abspath(root)
    picked = []
    for p in {os.path.abspath(x) for x in paths}:
        if p == root:
            try:
                picked += [os.path.join(root, n) for n in os.listdir(root)]
            except OSError:
                pass
        else:
            picked.append(p)
    ordered = sorted(set(picked), key=lambda p: p.count(os.sep))
    final = []
    for p in ordered:                    # shallowest first
        if any(p.startswith(k + os.sep) for k in final):
            continue                     # covered by an ancestor already
        final.append(p)
    excluded = {os.path.abspath(e) for e in excluded}
    items = []
    for p in final:
        rel = os.path.relpath(p, root)
        ex = sorted(e for e in excluded if e.startswith(p + os.sep))
        items.append((p, rel, ex))
    return items


def run_restore(items, target,
                log=print, status=lambda _s: None, progress=lambda _p: None,
                should_cancel=lambda: False):
    """Copy the given items from the backup into `target` (blocking).

    Returns (success, message, stats) with the same stats shape as
    run_rsync - files and bytes are summed across all items.
    """
    if RSYNC is None:
        return False, "rsync not found - install it (e.g. sudo apt install rsync)", {}
    if not items:
        return False, "Nothing selected to restore.", {}

    target = os.path.abspath(os.path.expanduser(target))
    try:
        os.makedirs(target, exist_ok=True)
    except OSError as e:
        return False, f"Could not create the target folder: {e}", {}

    total = len(items)
    stats_total = {}
    for i, item in enumerate(items, 1):
        src, rel = item[0], item[1]
        excludes = item[2] if len(item) > 2 else []
        src = os.path.abspath(os.path.expanduser(src))
        if not os.path.exists(src):
            log(f"! skipped (not in backup): {src}")
            continue
        rel = rel.strip(os.sep) or os.path.basename(src) or "restored"
        name = os.path.basename(src) or src
        dst = os.path.join(target, rel)

        status(f"Restoring {name} ({i}/{total})")
        # dirs are copied with a trailing slash so their CONTENTS land in
        # dst regardless of whether dst already exists; files are copied
        # to their exact target path.
        args = [RSYNC, "-a", "--info=progress2", "--stats"]
        for e in excludes:
            # anchored to the transfer root so only this item is affected
            pattern = "/" + os.path.relpath(e, src).replace(os.sep, "/")
            args.append(f"--exclude={pattern}")
        args.append(src.rstrip(os.sep) + os.sep
                    if os.path.isdir(src) else src)
        args.append(dst)
        log(f"$ {' '.join(args)}")
        try:
            proc = subprocess.Popen(args, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, bufsize=0)
        except OSError as e:
            return False, f"Could not start rsync: {e}", stats_total

        item_stats = {}
        cancelled = _pump(proc, log, status, progress, should_cancel, item_stats)
        rc = proc.wait()
        if cancelled:
            return False, ("Restore cancelled - anything finished before "
                           "cancelling was kept."), stats_total
        if rc != 0:
            return False, f"Restore failed for {name} (rsync exit code {rc}).", \
                stats_total
        for key, val in item_stats.items():
            stats_total[key] = stats_total.get(key, 0) + val

    return True, "Restore completed successfully.", stats_total


class RestoreWorker(QObject):
    """Runs run_restore in a QThread so the GUI never freezes."""

    log = pyqtSignal(str)
    status = pyqtSignal(str)
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)

    def __init__(self, items, target):
        super().__init__()
        self.items, self.target = items, target
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    @pyqtSlot()
    def run(self):
        ok, msg, _stats = run_restore(
            self.items, self.target,
            log=self.log.emit, status=self.status.emit,
            progress=self.progress.emit,
            should_cancel=lambda: self._cancelled,
        )
        self.finished.emit(ok, msg)
