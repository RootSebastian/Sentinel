"""System Monitor - live graphs for CPU, memory, network and disks,
in the same visual language as the rest of the app.
"""

import time

import psutil
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from sentinel.graphs import GraphWidget
from sentinel.theme import Pal
from sentinel.widgets import Card, UsageBar, human_bytes, label

RATE = lambda v: f"{human_bytes(v)}/s"


class MonitorScreen(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self._ticks = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        grid = QGridLayout()
        grid.setSpacing(14)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        root.addLayout(grid)
        root.addStretch(0)

        # ---- CPU -----------------------------------------------------------
        cpu_card = Card("CPU")
        cpu_card.set_expanding()
        h = QHBoxLayout()
        self.cpu_graph = GraphWidget("Total load", color=Pal.CPU)
        h.addWidget(self.cpu_graph, 3)
        cores_box = QVBoxLayout()
        cores_box.setSpacing(5)
        self.core_bars = []
        ncpu = psutil.cpu_count(logical=True) or 1
        for i in range(ncpu):
            bar = UsageBar(f"Core {i}", "", 0.0, accent=Pal.CPU,
                           name_color=Pal.DIM, bar_height=5, show_right=False)
            bar.name_lbl.setFont(self.name_font())
            cores_box.addWidget(bar)
            self.core_bars.append(bar)
        h.addLayout(cores_box, 2)
        cpu_card.vbox.addLayout(h)
        grid.addWidget(cpu_card, 0, 0)

        # ---- Memory ----------------------------------------------------------
        mem_card = Card("Memory")
        mem_card.set_expanding()
        h = QHBoxLayout()
        self.mem_graph = GraphWidget("RAM in use", color=Pal.MEM)
        h.addWidget(self.mem_graph, 3)
        right = QVBoxLayout()
        right.setSpacing(10)
        self.ram_bar = UsageBar("RAM", "", 0.0, accent=Pal.MEM)
        self.swap_bar = UsageBar("Swap", "", 0.0, accent=Pal.MEM,
                                 name_color=Pal.DIM)
        right.addWidget(self.ram_bar)
        right.addWidget(self.swap_bar)
        right.addStretch(1)
        h.addLayout(right, 2)
        mem_card.vbox.addLayout(h)
        grid.addWidget(mem_card, 0, 1)

        # ---- Network ----------------------------------------------------------
        net_card = Card("Network")
        net_card.set_expanding()
        self.down_graph = GraphWidget("Download", unit="B", fmt=RATE,
                                      color=Pal.DOWN)
        self.up_graph = GraphWidget("Upload", unit="B", fmt=RATE,
                                    color=Pal.UP)
        ng = QGridLayout()
        ng.addWidget(self.down_graph, 0, 0)
        ng.addWidget(self.up_graph, 0, 1)
        net_card.vbox.addLayout(ng)
        self.net_lbl = label("", size=12, color=Pal.DIM)
        self.net_lbl.setMargin(3)          # breathing room from card edge
        net_card.add(self.net_lbl)
        grid.addWidget(net_card, 1, 0)

        # ---- Disks ----------------------------------------------------------
        disk_card = Card("Disks")
        disk_card.set_expanding()
        self.disk_bars = []
        for part in psutil.disk_partitions():
            if part.fstype in ("squashfs", "tmpfs", "devtmpfs", "proc",
                               "sysfs") or "loop" in part.opts \
                    or "cdrom" in part.opts:
                continue
            try:
                u = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            bar = UsageBar(part.mountpoint,
                           f"{human_bytes(u.used)} / {human_bytes(u.total)}",
                           u.percent)
            disk_card.add(bar)
            disk_card.add_stretch(1)
            self.disk_bars.append((bar, part.mountpoint))
        if not self.disk_bars:
            # no partition table visible (containers etc.) - fall back to /
            try:
                u = psutil.disk_usage("/")
                bar = UsageBar("/", f"{human_bytes(u.used)} / {human_bytes(u.total)}",
                               u.percent)
                disk_card.add(bar)
                disk_card.add_stretch(1)
                self.disk_bars.append((bar, "/"))
            except (PermissionError, OSError):
                disk_card.add(label("No disks found.", size=12, color=Pal.FAINT))
        disk_card.add_stretch()
        grid.addWidget(disk_card, 1, 1)

        # ---- Temperatures (if the system exposes them) ------------------------
        try:
            temps = psutil.sensors_temperatures()
        except (AttributeError, OSError):
            temps = {}
        if temps:
            temp_card = Card("Temperatures")
            first = list(temps.keys())[0]
            entries = temps[first][:4]
            for e in entries:
                bar = UsageBar(e.label or first, f"{e.current:.0f}°C",
                               min(100.0, e.current),
                               accent=Pal.WARNING, bar_height=5)
                temp_card.add(bar)
            temp_card.add_stretch()
            grid.addWidget(temp_card, 2, 0, 1, 2)

        self._last_net = psutil.net_io_counters()
        self._last_t = time.monotonic()
        psutil.cpu_percent(percpu=True)               # prime
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self._tick()

    @staticmethod
    def name_font():
        from sentinel.theme import ui_font
        return ui_font(10.5)

    def _tick(self):
        cpus = psutil.cpu_percent(percpu=True)
        if cpus:
            self.cpu_graph.push(sum(cpus) / len(cpus))
            for bar, pct in zip(self.core_bars, cpus):
                bar.set_data(percent=pct)

        vm = psutil.virtual_memory()
        self.mem_graph.push(vm.percent)
        self.ram_bar.set_data(
            right=f"{human_bytes(vm.used)} / {human_bytes(vm.total)}",
            percent=vm.percent)
        sw = psutil.swap_memory()
        self.swap_bar.set_data(
            right=f"{human_bytes(sw.used)} / {human_bytes(sw.total)}",
            percent=sw.percent)

        net = psutil.net_io_counters()
        dt = max(time.monotonic() - self._last_t, 1e-3)
        down = max(0, net.bytes_recv - self._last_net.bytes_recv) / dt
        up = max(0, net.bytes_sent - self._last_net.bytes_sent) / dt
        self._last_net, self._last_t = net, time.monotonic()
        self.down_graph.push(down)
        self.up_graph.push(up)
        self.net_lbl.setText(f"\u2193 {human_bytes(down)}/s    \u2191 {human_bytes(up)}/s")
        self.net_lbl.setToolTip(
            f"Session totals:  \u2193 {human_bytes(net.bytes_recv)}   "
            f"\u2191 {human_bytes(net.bytes_sent)}")

        self._ticks += 1
        if self._ticks % 5 == 0:
            for bar, mount in self.disk_bars:
                try:
                    u = psutil.disk_usage(mount)
                    bar.set_data(
                        right=f"{human_bytes(u.used)} / {human_bytes(u.total)}",
                        percent=u.percent)
                except (PermissionError, OSError):
                    pass
