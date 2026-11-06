"""Dashboard - the friendly home screen.

Shows backup health at a glance, quick stats with sparklines, storage and
system info. Everything actionable is one click away.
"""

import os
import platform
import shutil
import time
from datetime import datetime, timezone

import psutil
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QGridLayout, QHBoxLayout, QPushButton,
                             QVBoxLayout, QWidget)

from sentinel import config
from sentinel.graphs import Sparkline
from sentinel.theme import Pal
from sentinel.widgets import (Card, UsageBar, dot_label, human_bytes, icon_label,
                             label, time_ago)


class DashboardScreen(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cfg = win.cfg

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # ---- hero -----------------------------------------------------
        self.hero = Card()
        self.hero.vbox.setContentsMargins(22, 18, 22, 18)
        hero_row = QHBoxLayout()
        hero_row.setSpacing(14)
        self.hero_icon = icon_label("shield", Pal.SUCCESS, 40)
        hero_row.addWidget(self.hero_icon)
        hero_txt = QVBoxLayout()
        hero_txt.setSpacing(2)
        self.hero_title = label("All backed up", size=19, bold=True)
        self.hero_sub = label("", size=13, color=Pal.DIM)
        hero_txt.addWidget(self.hero_title)
        hero_txt.addWidget(self.hero_sub)
        hero_row.addLayout(hero_txt, 1)

        self.setup_btn = QPushButton("Start setup")
        self.setup_btn.setObjectName("Primary")
        self.setup_btn.clicked.connect(self._run_setup)
        hero_row.addWidget(self.setup_btn)

        self.backup_btn = QPushButton("Back up now")
        self.backup_btn.setObjectName("Primary")
        self.backup_btn.clicked.connect(self._backup_now)
        hero_row.addWidget(self.backup_btn)

        settings_btn = QPushButton("Backup settings")
        settings_btn.setObjectName("Ghost")
        settings_btn.clicked.connect(lambda: self.win.go_to("backup"))
        hero_row.addWidget(settings_btn)

        self.hero.vbox.addLayout(hero_row)
        root.addWidget(self.hero)

        # ---- stat cards ------------------------------------------------
        grid = QGridLayout()
        grid.setSpacing(14)
        self.cpu_card = Card()
        self._stat_decorate(self.cpu_card, "CPU", "monitor")
        self.cpu_spark = Sparkline(Pal.CPU)
        self.cpu_card.vbox.addWidget(self.cpu_spark)

        self.mem_card = Card()
        self._stat_decorate(self.mem_card, "Memory", "drive")
        self.mem_spark = Sparkline(Pal.MEM)
        self.mem_card.vbox.addWidget(self.mem_spark)

        self.last_card = Card()
        self._stat_decorate(self.last_card, "Last backup", "backup")
        self.next_run_lbl = label("", size=11, color=Pal.FAINT)
        self.last_card.vbox.addWidget(self.next_run_lbl)
        self.hist_btn = QPushButton("History →")
        self.hist_btn.setObjectName("Ghost")
        self.hist_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hist_btn.clicked.connect(lambda: self.win.go_to("history"))
        self.last_card.vbox.addWidget(self.hist_btn)
        self.last_card.vbox.addStretch(1)

        self.dest_card = Card()
        self._stat_decorate(self.dest_card, "Backup destination", "folder")
        self.dest_bar = UsageBar("", "", 0.0)
        self.dest_card.vbox.addWidget(self.dest_bar)
        self.dest_card.vbox.addStretch(1)

        for i, c in enumerate((self.cpu_card, self.mem_card,
                               self.last_card, self.dest_card)):
            c.setMinimumHeight(148)
            c.set_expanding()          # equal heights across the row
            grid.addWidget(c, 0, i)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3, 1)
        root.addLayout(grid)

        # ---- storage + system -------------------------------------------
        bottom = QHBoxLayout()
        bottom.setSpacing(14)

        storage = Card("Storage")
        storage.set_expanding()
        self.storage_bars = []
        parts = [p for p in psutil.disk_partitions()
                 if p.fstype not in ("squashfs", "tmpfs", "devtmpfs",
                                     "proc", "sysfs")
                 and "loop" not in p.opts and "cdrom" not in p.opts]
        for part in parts[:3]:
            try:
                u = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            bar = UsageBar(part.mountpoint,
                           f"{human_bytes(u.used)} / {human_bytes(u.total)}",
                           u.percent)
            storage.add(bar)
            storage.add_stretch(1)
            self.storage_bars.append((bar, part.mountpoint))
        if not self.storage_bars:
            # no partition table visible (containers etc.) - fall back to the
            # volume that holds the backup destination (or /)
            try:
                mount = os.path.expanduser(self.cfg.get("destination") or "/")
                u = psutil.disk_usage(mount)
                bar = UsageBar("Backup volume",
                               f"{human_bytes(u.used)} / {human_bytes(u.total)}",
                               u.percent)
                storage.add(bar)
                storage.add_stretch(1)
                self.storage_bars.append((bar, mount))
            except (PermissionError, OSError):
                storage.add(label("No disks found.", size=12, color=Pal.FAINT))
                storage.add_stretch()
        bottom.addWidget(storage, 3)

        system = Card("System")
        system.set_expanding()
        self.sys_rows = {}
        for key, icon_name in (("uptime", "clock"), ("procs", "processes"),
                               ("swap", "drive"), ("os", "info")):
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(icon_label(icon_name, Pal.FAINT, 15))
            k = label(key.replace("os", "Platform").capitalize() + ":",
                      size=12, color=Pal.DIM)
            row.addWidget(k)
            v = label("—", size=12)
            row.addWidget(v, 1)
            system.vbox.addLayout(row)
            system.add_stretch(1)
            self.sys_rows[key] = v
        bottom.addWidget(system, 2)
        root.addLayout(bottom, 1)

        # ---- wiring ----------------------------------------------------
        if win.manager:
            win.manager.started.connect(self._on_backup_started)
            win.manager.finished.connect(self._on_backup_finished)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(2000)
        self.tick()

    @staticmethod
    def _stat_decorate(card, title, icon_name):
        card.vbox.setContentsMargins(16, 12, 16, 12)
        head = QHBoxLayout()
        head.addWidget(icon_label(icon_name, Pal.DIM, 15))
        head.addWidget(label(title, size=12, color=Pal.DIM))
        head.addStretch(1)
        card.vbox.addLayout(head)
        card.value_lbl = label("—", size=21)
        card.vbox.addWidget(card.value_lbl)
        card.sub_lbl = label("", size=11, color=Pal.FAINT, wrap=True)
        card.vbox.addWidget(card.sub_lbl)

    # ------------------------------------------------------------- update --
    def tick(self):
        self.cfg = config.load()
        # hero
        self._refresh_hero()
        # stats
        cpu = psutil.cpu_percent()
        vm = psutil.virtual_memory()
        self.cpu_spark.push(cpu)
        self.mem_spark.push(vm.percent)
        self.cpu_card.value_lbl.setText(f"{cpu:.0f}%")
        self.mem_card.value_lbl.setText(f"{vm.percent:.0f}%")
        ago = time_ago(self.cfg.get("last_backup"))
        if self.cfg.get("last_backup") and ago:
            dt = datetime.fromisoformat(self.cfg["last_backup"])
            self.last_card.value_lbl.setText(ago)
            self.last_card.value_lbl.setStyleSheet(
                f"color: {Pal.TEXT}; background: transparent;")
            self.last_card.sub_lbl.setText(
                dt.astimezone().strftime("%b %d, %H:%M"))
        else:
            self.last_card.value_lbl.setText("Never")
            self.last_card.value_lbl.setStyleSheet(
                f"color: {Pal.WARNING}; background: transparent;")
            self.last_card.sub_lbl.setText("No backups yet")
        sched, when = self.cfg.get("schedule", "manual"), \
            self.cfg.get("schedule_time", "03:00")
        self.next_run_lbl.setText(
            {"manual": "Manual backups only",
             "hourly": "Runs every hour while open",
             "daily": f"Runs daily at {when}",
             "weekly": f"Runs weekly at {when}"}.get(sched, ""))
        dest = self.cfg.get("destination")
        if dest and os.path.isdir(os.path.expanduser(dest)):
            try:
                u = shutil.disk_usage(os.path.expanduser(dest))
                self.dest_card.value_lbl.setText(human_bytes(u.free))
                self.dest_card.value_lbl.setStyleSheet(
                    f"color: {Pal.TEXT}; background: transparent;")
                self.dest_card.sub_lbl.setText(dest)
                self.dest_bar.set_data(
                    name="Used space",
                    right=f"{100 * u.used / u.total:.0f}%",
                    percent=100 * u.used / u.total)
            except OSError:
                self.dest_card.value_lbl.setText("Unavailable")
                self.dest_card.sub_lbl.setText(dest)
        else:
            self.dest_card.value_lbl.setText("Not set")
            self.dest_card.value_lbl.setStyleSheet(
                f"color: {Pal.WARNING}; background: transparent;")
            self.dest_card.sub_lbl.setText("Choose a destination in setup")
            self.dest_bar.set_data(name="", right="", percent=0)
        # storage bars
        for bar, mount in self.storage_bars:
            try:
                u = psutil.disk_usage(mount)
                bar.set_data(right=f"{human_bytes(u.used)} / {human_bytes(u.total)}",
                             percent=u.percent)
            except (PermissionError, OSError):
                pass
        # system rows
        up = time.time() - psutil.boot_time()
        d, h, m = int(up // 86400), int(up % 86400 // 3600), int(up % 3600 // 60)
        self.sys_rows["uptime"].setText(f"{d}d {h}h {m}m" if d else f"{h}h {m}m")
        self.sys_rows["procs"].setText(
            f"{len(psutil.pids())} running")
        sw = psutil.swap_memory()
        self.sys_rows["swap"].setText(
            f"{human_bytes(sw.used)} / {human_bytes(sw.total)}")
        self.sys_rows["os"].setText(
            f"{platform.system()} {platform.release()}")

    def _refresh_hero(self):
        running = self.win.manager and self.win.manager.is_running()
        if running:
            self.hero_icon.set_default = None
            self._set_hero(Pal.ACCENT, "Backup in progress…",
                           "You can keep working - this runs in the background.")
            self.backup_btn.hide()
            self.setup_btn.hide()
            return
        if not self.cfg.get("onboarded"):
            self._set_hero(Pal.WARNING, "Let's set things up",
                           "Pick your folders and a destination - takes a minute.")
            self.backup_btn.hide()
            self.setup_btn.show()
            return
        self.setup_btn.hide()
        self.backup_btn.show()
        n = len(self.cfg.get("sources") or [])
        folders = f"{n} folder{'s' if n != 1 else ''}"
        if self.cfg.get("last_backup"):
            self._set_hero(Pal.SUCCESS, "Your files are backed up",
                           f"{folders} protected · Last backup "
                           f"{time_ago(self.cfg['last_backup'])}")
        else:
            self._set_hero(Pal.WARNING, "No backups yet",
                           f"{folders} selected · Run your first backup")

    def _set_hero(self, color, title, sub):
        from sentinel.theme import icon as _icon
        self.hero_icon.setPixmap(_icon("shield", color, 40).pixmap(40, 40))
        self.hero_title.setText(title)
        if len(sub) > 85:                        # keep the hero tidy
            sub = sub[: 84] + "…"
        self.hero_sub.setText(sub)

    # ------------------------------------------------------------- actions --
    def _run_setup(self):
        self.win.open_wizard()

    def _backup_now(self):
        self.win.manager.start()

    def _on_backup_started(self):
        self.tick()

    def _on_backup_finished(self, ok, msg):
        self.tick()
