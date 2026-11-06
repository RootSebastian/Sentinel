"""Settings persistence. Stored as JSON in ~/.config/sentinel/config.json."""

import json
import os

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "sentinel")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
    "sources": [],             # folders to back up
    "destination": "",         # where backups go
    "mode": "incremental",     # incremental | mirror | full
    "schedule": "manual",      # manual | hourly | daily | weekly
    "schedule_time": "03:00",  # HH:MM for daily/weekly runs
    "last_backup": None,       # ISO timestamp (UTC) of last completed run
    "onboarded": False,        # has the user finished the first-run wizard?
    "notifications": True,     # desktop notifications for backup results
    "update_check": True,      # quietly check GitHub for new versions on startup
    "theme": "midnight",       # active color theme (see theme.THEMES)
}


def use_dir(path):
    """Point config at another directory (used by screenshot tooling/tests)."""
    global CONFIG_DIR, CONFIG_FILE
    CONFIG_DIR = path
    CONFIG_FILE = os.path.join(path, "config.json")


def load():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_FILE) as f:
            loaded = json.load(f)
        cfg.update({k: v for k, v in loaded.items() if k in DEFAULTS})
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return cfg


def save(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_FILE)
