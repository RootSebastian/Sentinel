"""Append-only log of backup runs, stored next to the config file.

Each record describes one run: when it started and finished, what was
backed up, how much data moved and how it ended. The History screen
renders this file, and the headless `--backup-now` mode (systemd timer /
cron) writes to it too, so scheduled runs show up in the GUI.

The file is tiny JSON, rewritten atomically on every change and capped at
`MAX_RECORDS` runs. A corrupted file is treated as empty - history is a
convenience, never a prerequisite for backing up.
"""

import json
import os
import uuid
from datetime import datetime, timezone

from sentinel import config

MAX_RECORDS = 60

#: status key -> (color kind for widgets, human label)
STATUS_LABELS = {
    "completed": "Completed",
    "warnings": "Completed with warnings",
    "cancelled": "Cancelled",
    "failed": "Failed",
    "running": "Running…",
}

#: statuses that mean the backup destination holds a usable copy
OK_STATUSES = ("completed", "warnings")


def _path():
    # reads config.CONFIG_DIR at call time so tests (config.use_dir) work
    return os.path.join(config.CONFIG_DIR, "history.json")


def _read_all():
    try:
        with open(_path()) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _write_all(records):
    os.makedirs(config.CONFIG_DIR, exist_ok=True)
    tmp = _path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(records[-MAX_RECORDS:], f, indent=2)
    os.replace(tmp, _path())


def load():
    """All recorded runs, newest first."""
    return sorted(_read_all(), key=lambda r: r.get("started", ""), reverse=True)


def begin(cfg):
    """Open a record for a run that is about to start. Returns its id."""
    rec = {
        "id": uuid.uuid4().hex[:12],
        "started": datetime.now(timezone.utc).isoformat(),
        "finished": None,
        "duration_s": None,
        "mode": cfg.get("mode", "incremental"),
        "sources": list(cfg.get("sources") or []),
        "dest": cfg.get("destination") or "",
        "status": "running",
        "files": None,
        "bytes": None,
        "message": None,
    }
    records = _read_all()
    records.append(rec)
    _write_all(records)
    return rec["id"]


def complete(run_id, status, stats=None, message=None):
    """Fill in the outcome of a run opened with begin().

    Unknown status keys are recorded as "failed" so the log never lies.
    """
    stats = stats or {}
    records = _read_all()
    for rec in records:
        if rec.get("id") == run_id:
            rec["finished"] = datetime.now(timezone.utc).isoformat()
            started = rec.get("started")
            if started:
                t0 = datetime.fromisoformat(started)
                rec["duration_s"] = round(
                    (datetime.now(timezone.utc) - t0).total_seconds(), 1)
            rec["status"] = status if status in STATUS_LABELS else "failed"
            rec["files"] = stats.get("files")
            rec["bytes"] = stats.get("bytes")
            rec["message"] = message
            break
    _write_all(records)


def clear():
    """Forget all history (the backups themselves are untouched)."""
    _write_all([])


def latest_ok():
    """The newest run that produced a usable backup, or None."""
    for rec in load():
        if rec.get("status") in OK_STATUSES:
            return rec
    return None
