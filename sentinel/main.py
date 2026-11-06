#!/usr/bin/env python3
"""Sentinel - automatic backups + friendly system monitor for Linux.

Run the app (from the repository root):
    python -m sentinel            (or: python run.py, or just `sentinel`
                                    after `pip install -e .`)

Headless backup (used by the systemd timer / cron):
    sentinel --backup-now

GUI and headless mode share the same engine, config and history log.
"""

import sys


def main():
    if "--backup-now" in sys.argv[1:]:
        return headless_backup()

    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    from sentinel import config, theme
    from sentinel.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Sentinel")
    app.setDesktopFileName("sentinel")
    theme.apply(app)

    win = MainWindow()
    win.show()

    # quiet update check shortly after launch (silently skips when the
    # user turned it off in Settings, and never complains when offline)
    if config.load().get("update_check", True):
        from sentinel import updater
        QTimer.singleShot(1500, lambda: updater.startup_check(win))

    return app.exec()


def headless_backup():
    """Run the configured backup without the GUI (systemd/cron entrypoint).

    The run is written to the history log, so it shows up in the History
    screen the next time the app is opened.
    """
    from datetime import datetime, timezone

    from sentinel import config, history
    from sentinel.backup_engine import run_rsync

    cfg = config.load()
    if not cfg.get("sources") or not cfg.get("destination"):
        print("No backup configured yet - open the app once and finish setup.")
        return 1

    run_id = history.begin(cfg)
    ok, msg, stats = run_rsync(cfg["sources"], cfg["destination"], cfg["mode"])
    if ok:
        cfg["last_backup"] = datetime.now(timezone.utc).isoformat()
        config.save(cfg)
    history.complete(run_id, "completed" if ok else "failed",
                     stats=stats, message=msg)
    print(msg)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
