#!/usr/bin/env python3
"""Render screenshots of every Sentinel screen without a display.

Uses an isolated demo config (never touches your real settings) and a
small demo dataset, then grabs each screen as PNG - including the dashboard
under every available color theme.

Usage:
    QT_QPA_PLATFORM=offscreen python screenshot.py [output_dir]
"""

import glob
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone

# must be set before QApplication is created
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs", "screenshots")

DEMO_HOME = os.path.join(tempfile.gettempdir(), "sentinel-demo-home")
DEMO_DEST = os.path.join(tempfile.gettempdir(), "sentinel-demo-backup")
DEMO_CFG = os.path.join(tempfile.gettempdir(), "sentinel-demo-cfg")


def build_demo_data():
    for d in ("Documents", "Pictures", "Projects"):
        os.makedirs(os.path.join(DEMO_HOME, d), exist_ok=True)
    # a few real files so rsync has something to do
    docs = os.path.join(DEMO_HOME, "Documents")
    with open(os.path.join(docs, "notes.txt"), "w") as f:
        f.write("shopping list\n" * 400)
    with open(os.path.join(docs, "budget-2026.csv"), "w") as f:
        f.write("month,income,expense\n" + "Jan,3200,2410\n" * 30)
    pics = os.path.join(DEMO_HOME, "Pictures")
    with open(os.path.join(pics, "vacation-2026.bin"), "wb") as f:
        f.write(os.urandom(180_000))
    prj = os.path.join(DEMO_HOME, "Projects")
    with open(os.path.join(prj, "main.py"), "w") as f:
        f.write("print('hello')\n" * 200)
    os.makedirs(DEMO_DEST, exist_ok=True)


def write_demo_config():
    from sentinel import config
    config.use_dir(DEMO_CFG)
    os.makedirs(DEMO_CFG, exist_ok=True)
    cfg = config.load()
    cfg.update({
        "sources": [os.path.join(DEMO_HOME, d)
                    for d in ("Documents", "Pictures", "Projects")],
        "destination": DEMO_DEST,
        "mode": "incremental",
        "schedule": "daily",
        "schedule_time": "03:00",
        "last_backup": (datetime.now(timezone.utc)
                        - timedelta(hours=2)).isoformat(),
        "onboarded": True,
        "notifications": True,
        "theme": "midnight",
    })
    config.save(cfg)
    return cfg


def pump(app, seconds):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QApplication
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        # processEvents() skips DeferredDelete events - flush them like a
        # real event loop would, or widgets replaced mid-run (history rows,
        # theme switches) would linger as zombies in the grabs
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        time.sleep(0.02)


def shot(widget, name):
    path = os.path.abspath(os.path.join(OUT, name))
    pm = widget.grab()
    pm.save(path)
    print(f"saved {path}  ({pm.width()}x{pm.height()})", flush=True)


def _burn(stop):
    # bursty, not saturating: a busy loop would starve the (throttled) CPU
    # this app runs on and make everything crawl during screenshots
    while not stop.is_set():
        for _ in range(2):
            sum(i * i for i in range(2000))
        time.sleep(0.03)


def fill_graphs(app, win, n=60):
    """Push n samples into the live graphs (with some real CPU load so the
    charts show meaningful curves instead of flat lines)."""
    import psutil
    stop = threading.Event()
    threading.Thread(target=_burn, args=(stop,), daemon=True).start()
    psutil.cpu_percent(percpu=True)
    for _ in range(n):
        win.screens["dashboard"].tick()
        win.screens["monitor"]._tick()
        app.processEvents()
        time.sleep(0.04)
    stop.set()
    time.sleep(0.1)


def main():
    os.makedirs(OUT, exist_ok=True)
    for old in glob.glob(os.path.join(OUT, "*.png")):
        os.remove(old)
    build_demo_data()
    write_demo_config()

    # run a real backup so the log/activity screenshot shows genuine output
    from sentinel import config, history
    from sentinel.backup_engine import run_rsync
    cfg = config.load()
    lines = []
    ok, msg, stats = run_rsync(cfg["sources"], cfg["destination"],
                               cfg["mode"], log=lines.append)
    print("demo backup:", "ok" if ok else "FAILED")

    # seed the history log with a plausible set of past runs (the seeded
    # timestamps are in the past so "When" shows varied, realistic dates)
    from datetime import datetime as _dt
    for status, days_ago, files, size, mode in (
            ("completed", 0, stats.get("files"), stats.get("bytes"),
             "incremental"),
            ("warnings", 1, 214, 1_930_000_000, "incremental"),
            ("completed", 2, 388, 2_100_000_000, "full"),
            ("failed", 3, 0, 0, "incremental"),
    ):
        rid = history.begin({"mode": mode, "sources": cfg["sources"],
                             "destination": cfg["destination"]})
        # shift the record into the past for a realistic timeline
        history.complete(rid, status,
                         stats={"files": files, "bytes": size},
                         message=msg if days_ago == 0 else
                         ("Completed with warnings (rsync code 24: some "
                          "files vanished or could not be read)."
                          if status == "warnings" else
                          "Backup failed (rsync exit code 23)."))
        if days_ago:
            records = history._read_all()
            for rec in records:
                if rec["id"] == rid:
                    rec["started"] = (_dt.now(timezone.utc) -
                                      timedelta(days=days_ago)).isoformat()
                    rec["finished"] = rec["started"]
            history._write_all(records)

    from PyQt6.QtWidgets import QApplication  # noqa
    from sentinel import theme
    app = QApplication([])
    theme.apply(app)

    from sentinel.ui.main_window import MainWindow
    win = MainWindow(demo=True)
    win.resize(1220, 780)
    win.show()
    pump(app, 0.5)

    fill_graphs(app, win)
    shot(win, "01-dashboard.png")

    win.go_to("backup")
    bk = win.screens["backup"]
    # show the activity log with the real rsync output, in a consistent
    # "finished" state
    bk.details_btn.setChecked(True)
    bk._toggle_details(True)
    for line in lines:
        bk.log.appendPlainText(line)
    bk._on_finished(ok, msg)
    pump(app, 0.3)
    shot(win, "02-backup.png")

    # history & restore screen (uses the seeded history above)
    win.screens["history"].refresh()
    win.go_to("history")
    pump(app, 0.4)
    shot(win, "03-history.png")

    # the advanced restore picker with a plausible selection
    from PyQt6.QtCore import Qt
    from sentinel.ui.restore_dialog import RestoreDialog
    dlg = RestoreDialog(DEMO_DEST, win)
    dlg.resize(780, 560)
    dlg.show()
    pump(app, 0.6)
    check = int(Qt.ItemDataRole.CheckStateRole)
    docs = dlg.model.index(os.path.join(DEMO_DEST, "Documents"))
    dlg.model.setData(docs, Qt.CheckState.Checked.value, check)
    leaf = dlg.model.index(os.path.join(DEMO_DEST, "Pictures",
                                        "vacation-2026.bin"))
    dlg.model.setData(leaf, Qt.CheckState.Checked.value, check)
    pump(app, 0.4)
    shot(dlg, "04-restore-picker.png")
    dlg.hide()

    win.go_to("processes")
    import psutil
    psutil.cpu_percent(percpu=True)
    time.sleep(1.1)                       # let cpu_percent get a real sample
    win.screens["processes"].refresh()
    win.screens["processes"].table.selectRow(0)   # show End task as active
    pump(app, 0.4)
    shot(win, "05-processes.png")

    win.go_to("monitor")
    pump(app, 0.4)
    shot(win, "06-monitor.png")

    win.go_to("settings")
    pump(app, 0.3)
    shot(win, "07-settings.png")

    # wizard pages
    from sentinel import config as _cfg
    fresh = os.path.join(tempfile.gettempdir(), "sentinel-demo-cfg-fresh")
    _cfg.use_dir(fresh)
    os.makedirs(fresh, exist_ok=True)
    # the wizard lists the user's real home folders - make sure a typical
    # set exists so the screenshot is representative
    home = os.path.expanduser("~")
    for d in ("Documents", "Pictures", "Videos", "Music", "Desktop",
              "Downloads", "Projects"):
        os.makedirs(os.path.join(home, d), exist_ok=True)
    from sentinel.ui.wizard import FirstRunWizard
    wiz = FirstRunWizard(_cfg.load())
    wiz.show()
    pump(app, 0.3)
    shot(wiz, "08-welcome.png")
    for i, name in ((1, "09-wizard-folders.png"),
                    (2, "10-wizard-destination.png"),
                    (3, "11-wizard-schedule.png")):
        wiz.goto(i)
        if i == 1 and wiz.what_checks:
            wiz.what_checks[0].setChecked(True)   # show a valid, enabled state
        pump(app, 0.2)
        shot(wiz, name)
    wiz.close()
    _cfg.use_dir(DEMO_CFG)

    # dashboard under every remaining theme (midnight is shot 01)
    for i, key in enumerate(("graphite", "nord", "dracula", "mocha",
                             "rosepine", "daylight", "paper"), start=12):
        win.set_theme(key)
        win.go_to("dashboard")
        pump(app, 0.4)
        fill_graphs(app, win, n=50)
        shot(win, f"{i:02d}-theme-{key}.png")

    print("\nAll screenshots rendered to", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
