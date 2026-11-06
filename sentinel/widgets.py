"""Reusable styled widgets built on top of the Sentinel design system."""

from PyQt6 import sip
from PyQt6.QtCore import Qt, pyqtSignal, QRectF
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                             QRadioButton, QSizePolicy, QVBoxLayout, QWidget)

from sentinel.theme import Pal, icon, ui_font, NO_PEN, NO_BRUSH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def human_bytes(n):
    n = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024:
            return f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:,.1f} PiB"


def time_ago(iso_or_dt):
    from datetime import datetime, timezone
    if iso_or_dt is None:
        return None
    dt = iso_or_dt if hasattr(iso_or_dt, "tzinfo") else datetime.fromisoformat(iso_or_dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    if secs < 0:
        secs = 0
    if secs < 60:
        return "just now"
    if secs < 3600:
        m = int(secs // 60)
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if secs < 86400:
        h = int(secs // 3600)
        return f"{h} hour{'s' if h != 1 else ''} ago"
    d = int(secs // 86400)
    if d < 30:
        return f"{d} day{'s' if d != 1 else ''} ago"
    return dt.strftime("%b %d, %Y")


def label(text="", size=13.0, color=None, bold=False, dim=False,
          faint=False, wrap=False, mono=False):
    """Themed QLabel factory."""
    lbl = QLabel(text)
    if mono:
        from sentinel.theme import mono_font
        lbl.setFont(mono_font(size))
    else:
        lbl.setFont(ui_font(size, weight=__weight(bold)))
    if color is None:
        color = Pal.DIM if dim else Pal.FAINT if faint else Pal.TEXT
    lbl.setStyleSheet(f"color: {color}; background: transparent;")
    if wrap:
        lbl.setWordWrap(True)
    return lbl


def __weight(bold):
    from PyQt6.QtGui import QFont
    return QFont.Weight.DemiBold if bold else QFont.Weight.Normal


def icon_label(name, color=None, size=18):
    if color is None:
        color = Pal.DIM
    lbl = QLabel()
    lbl.setPixmap(icon(name, color, size).pixmap(size, size))
    lbl.setFixedSize(size + 4, size + 4)
    lbl.setStyleSheet("background: transparent;")
    return lbl


def dot_label(text, color=None, size=13.0, bold=False):
    if color is None:
        color = Pal.SUCCESS
    lbl = label(text, size=size, bold=bold)
    lbl.setText(f'<span style="color:{color}">&#9679;</span>&nbsp;&nbsp;{text}')
    return lbl


def hline():
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"background: {Pal.BORDER}; border: none; max-height: 1px;")
    line.setFixedHeight(1)
    return line


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------
class Card(QFrame):
    """Rounded surface card with optional title row and optional right widget."""

    def __init__(self, title=None, right=None, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(16, 14, 16, 14)
        self.vbox.setSpacing(10)
        if title or right:
            row = QHBoxLayout()
            row.setSpacing(8)
            if title:
                row.addWidget(label(title, size=14, bold=True))
            row.addStretch(1)
            if right is not None:
                row.addWidget(right)
            self.vbox.addLayout(row)

    def set_expanding(self):
        """Let this card grow vertically (for cards inside stretched layouts)."""
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Expanding)

    def add(self, item):
        if isinstance(item, QWidget):
            self.vbox.addWidget(item)
        else:
            self.vbox.addLayout(item)

    def add_stretch(self, n=1):
        self.vbox.addStretch(n)


class StatCard(Card):
    """Compact metric card: small title, big value, dim subtitle."""

    def __init__(self, title, icon_name=None, parent=None):
        self._right_btn = None
        super().__init__(parent=parent)
        # replace margins for a tighter card
        self.vbox.setContentsMargins(16, 12, 16, 12)
        head = QHBoxLayout()
        head.setSpacing(8)
        if icon_name:
            head.addWidget(icon_label(icon_name, Pal.DIM, 16))
        head.addWidget(label(title, size=12, color=Pal.DIM))
        head.addStretch(1)
        self.vbox.addLayout(head)

        self.value_lbl = label("—", size=22)
        self.value_lbl.setFont(ui_font(22, weight=__weight(False)))
        self.vbox.addWidget(self.value_lbl)
        self.sub_lbl = label("", size=12, color=Pal.FAINT, wrap=True)
        self.vbox.addWidget(self.sub_lbl)

    def set_value(self, text, color=Pal.TEXT):
        self.value_lbl.setText(text)
        self.value_lbl.setStyleSheet(f"color: {color}; background: transparent;")

    def set_sub(self, text):
        self.sub_lbl.setText(text)


# ---------------------------------------------------------------------------
# Option card (selectable choice, e.g. backup mode / schedule)
# ---------------------------------------------------------------------------
class OptionCard(QFrame):
    """A clickable choice card. Behaves like a radio button but looks like a
    titled card with a description - much friendlier than a combo box."""

    toggled = pyqtSignal(bool)

    def __init__(self, title, description="", badge=None, parent=None):
        super().__init__(parent)
        self.setObjectName("OptionCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checking = False

        self.radio = QRadioButton()
        self.radio.setFixedSize(16, 16)
        self.radio.setStyleSheet("QRadioButton::indicator { width: 0; height: 0; }"
                                 "QRadioButton { background: transparent; }")
        self.radio.toggled.connect(self._on_toggle)

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(14, 12, 14, 12)
        vbox.setSpacing(3)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(self.radio)
        head.addWidget(label(title, size=13, bold=True))
        if badge:
            b = label(badge, size=10, color=Pal.ON_ACCENT)
            b.setStyleSheet(f"background: {Pal.ACCENT}; color: {Pal.ON_ACCENT};"
                            "border-radius: 6px; padding: 2px 8px;")
            head.addWidget(b)
        head.addStretch(1)
        vbox.addLayout(head)
        if description:
            desc = label(description, size=12, color=Pal.DIM, wrap=True)
            desc.setIndent(24)          # align under the title
            vbox.addWidget(desc)

    def _on_toggle(self, checked):
        self._refresh(checked)
        if not self._checking:
            self.toggled.emit(checked)

    def _refresh(self, checked):
        self.setProperty("selected", checked)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_checked(self, checked):
        self._checking = True
        self.radio.setChecked(checked)
        self._checking = False
        self._refresh(checked)

    def is_checked(self):
        return self.radio.isChecked()

    def mousePressEvent(self, event):
        self.radio.toggle()
        # a toggled() slot may rebuild the UI and delete this card - never
        # touch the C++ side of a widget that may have been deleted
        if not sip.isdeleted(self):
            super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# Usage bar (disk / memory / per-core CPU)
# ---------------------------------------------------------------------------
class UsageBar(QWidget):
    """Label row + slim rounded bar. Color shifts amber > 80%, red > 90%."""

    def __init__(self, name="", right="", percent=0.0, accent=None,
                 name_color=None, bar_height=7, show_right=True):
        super().__init__()
        self.percent = percent
        self.accent = accent or Pal.ACCENT
        self.bar_height = bar_height
        self._name = name
        self._right = right
        self._show_right = show_right
        self._name_color = name_color or Pal.TEXT

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(4)
        row = QHBoxLayout()
        self.name_lbl = label(name, size=12, color=name_color)
        row.addWidget(self.name_lbl)
        row.addStretch(1)
        self.right_lbl = label(right, size=12, color=Pal.DIM)
        row.addWidget(self.right_lbl)
        vbox.addLayout(row)
        if not show_right:
            self.right_lbl.hide()
        self.setMinimumHeight(bar_height + 28)

    def set_data(self, name=None, right=None, percent=None):
        if name is not None:
            self._name = name
            self.name_lbl.setText(name)
        if right is not None:
            self._right = right
            self.right_lbl.setText(right)
        if percent is not None:
            self.percent = max(0.0, min(100.0, float(percent)))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        y = self.height() - self.bar_height
        r = self.bar_height / 2

        # track
        p.setPen(NO_PEN)
        p.setBrush(QColor(Pal.FIELD))
        p.drawRoundedRect(QRectF(0, y, w, self.bar_height), r, r)

        # fill
        if self.percent > 0.5:
            color = self.accent
            if self.percent > 90:
                color = Pal.DANGER
            elif self.percent > 80:
                color = Pal.WARNING
            fw = max(self.bar_height, w * self.percent / 100.0)
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(0, y, fw, self.bar_height), r, r)
        p.end()


# ---------------------------------------------------------------------------
# Status line helper
# ---------------------------------------------------------------------------
def status_color(kind):
    """Resolve a status color from the ACTIVE theme (never cached)."""
    return {"ok": Pal.SUCCESS, "warn": Pal.WARNING, "bad": Pal.DANGER,
            "idle": Pal.DIM, "accent": Pal.ACCENT}[kind]
