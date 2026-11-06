#!/usr/bin/env python3
"""Regenerate the Sentinel application icon (data/icons/sentinel.png).

Draws the shield glyph from the design system on a rounded accent tile,
so the launcher icon always matches the app's default (Midnight) theme.
Run from the repository root:  python tools/make_icon.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

from sentinel import theme


def make_icon(size=256):
    t = theme.THEMES[theme.DEFAULT_THEME]
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)

    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # rounded accent tile
    radius = size * 0.22
    tile = QRectF(0, 0, size, size)
    path = QPainterPath()
    path.addRoundedRect(tile, radius, radius)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(t.accent))
    p.drawPath(path)

    # shield glyph in the on-accent color, drawn large and centered
    glyph = QPixmap(size, size)
    glyph.fill(Qt.GlobalColor.transparent)
    g = QPainter(glyph)
    g.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(t.on_accent))
    pen.setWidthF(size / 11.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    g.setPen(pen)
    theme._shield(g, size)
    g.end()

    # scale the glyph to ~70% and center it on the tile
    inner = glyph.scaled(int(size * 0.66), int(size * 0.66),
                         Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    margin = (size - inner.width()) // 2
    p.drawPixmap(margin, margin, inner)
    p.end()
    return pm


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    _app = QApplication([])          # QPixmap needs a QGuiApplication
    out = os.path.join(os.path.dirname(__file__), "..", "data", "icons",
                       "sentinel.png")
    pm = make_icon(256)
    pm.save(os.path.abspath(out))
    print(f"wrote {os.path.abspath(out)} ({pm.width()}x{pm.height()})")
