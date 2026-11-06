"""Scrolling history graphs (CPU / memory / network style) with gradient
fills, drawn from the theme palette."""

from collections import deque

from PyQt6.QtCore import Qt
from PyQt6.QtGui import (QBrush, QColor, QLinearGradient, QPainter,
                         QPainterPath, QPen, QFont)
from PyQt6.QtWidgets import QWidget

from sentinel.theme import (Pal, nice_ceil, ui_font, NO_PEN, NO_BRUSH, ANTIALIAS,
                   TRANSPARENT)

# alignment as plain ints - avoids per-paint enum conversion
ALIGN_LEFT_V = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
ALIGN_RIGHT_V = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class GraphWidget(QWidget):
    """Live line chart.

    unit="%"  -> fixed 0-100 scale
    unit="B"  -> auto scale with nice ceilings (for byte rates)
    pass fmt  -> value formatter, e.g. lambda v: f"{v:.0f} MiB/s"
    """

    def __init__(self, title="", unit="%", color=None, fmt=None,
                 maxlen=120, show_value=True, small=False, parent=None):
        super().__init__(parent)
        self.title = title
        self.unit = unit
        self.color = QColor(color or Pal.CPU)
        self.fmt = fmt or (lambda v: f"{v:.1f}{'%' if unit == '%' else ''}")
        self.maxlen = maxlen
        self.show_value = show_value
        self.small = small
        self.values = deque(maxlen=maxlen)
        if small:
            self.setMinimumSize(80, 34)
        else:
            self.setMinimumSize(220, 120)

    # -- data ---------------------------------------------------------------
    def push(self, value):
        self.values.append(max(0.0, float(value)))
        self.update()

    def clear(self):
        self.values.clear()
        self.update()

    # -- painting -----------------------------------------------------------
    def _scale_max(self):
        if self.unit == "%":
            return 100.0
        peak = max(self.values) if self.values else 0.0
        return nice_ceil(peak * 1.15) if peak > 0 else 1.0

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(ANTIALIAS)
        w, h = self.width(), self.height()

        # inset panel - only for full-size graphs; the small sparkline
        # variant draws naked so it never reads as a box-within-a-box
        radius = 8 if not self.small else 6
        if not self.small:
            p.setPen(NO_PEN)
            p.setBrush(QColor(Pal.FIELD))
            p.drawRoundedRect(0, 0, w, h, radius, radius)

        pad_top = 24 if self.show_value or self.title else 8
        graph_h = h - pad_top - 8
        if graph_h < 8:
            p.end()
            return

        # grid lines
        if not self.small:
            grid = QColor(Pal.BORDER)
            grid.setAlpha(110)
            pen = QPen(grid, 1)
            p.setPen(pen)
            for i in range(1, 4):
                y = pad_top + int(graph_h * i / 4)
                p.drawLine(6, y, w - 6, y)

        if not self.values:
            self._draw_text(p)
            p.end()
            return

        vmax = self._scale_max()
        n = len(self.values)
        step = (w - 14) / max(1, self.maxlen - 1)
        pts = []
        for i, v in enumerate(self.values):
            x = 7 + i * step
            y = pad_top + graph_h - int((v / vmax) * graph_h)
            pts.append((x, max(pad_top + 1, y)))

        if len(pts) == 1:
            pts.append((pts[0][0] + 0.5, pts[0][1]))

        # gradient fill under the line
        fill = QPainterPath()
        base = pad_top + graph_h
        fill.moveTo(pts[0][0], base - 1)
        for x, y in pts:
            fill.lineTo(x, y)
        fill.lineTo(pts[-1][0], base - 1)
        fill.closeSubpath()

        grad = QLinearGradient(0, pad_top, 0, base)
        top = QColor(self.color)
        top.setAlpha(120 if not self.small else 70)
        bottom = QColor(self.color)
        bottom.setAlpha(0)
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bottom)
        p.setPen(NO_PEN)
        p.setBrush(QBrush(grad))
        p.drawPath(fill)

        # the line itself
        line = QPainterPath()
        line.moveTo(pts[0][0], pts[0][1])
        for x, y in pts[1:]:
            line.lineTo(x, y)
        p.setPen(QPen(self.color, 2 if not self.small else 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(line)

        self._draw_text(p)
        p.end()

    def _draw_text(self, p):
        if self.small:
            return
        p.setRenderHint(ANTIALIAS, False)
        if self.title:
            p.setFont(ui_font(11))
            p.setPen(QColor(Pal.DIM))
            p.drawText(10, 8, self.width() - 20, 16, ALIGN_LEFT_V, self.title)
        if self.show_value:
            p.setFont(ui_font(11.5, weight=QFont.Weight.DemiBold))
            p.setPen(QColor(self.color))
            text = self.fmt(self.values[-1]) if self.values else "—"
            p.drawText(10, 8, self.width() - 20, 16, ALIGN_RIGHT_V, text)


class Sparkline(GraphWidget):
    """Compact variant for stat cards: no title, thin, gradient only."""

    def __init__(self, color=None, maxlen=90, parent=None):
        super().__init__(title="", unit="%", color=color, maxlen=maxlen,
                         show_value=False, small=True, parent=parent)
