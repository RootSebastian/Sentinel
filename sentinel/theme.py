"""Sentinel design system.

Single source of truth for the whole look of the app: the color themes,
typography, the global stylesheet (QSS) and a small hand-drawn icon set.

Eight hand-tuned themes ship with the app - six dark and two light - and the
palette is fully dynamic: ``Pal.ACCENT`` (and friends) always resolve to the
*currently active* theme, so switching themes is instant and app-wide.

    theme.set_theme("dracula", app)      # live switch, no restart needed

Derived shades (hover overlays, tints, selection colors) are blended from the
core palette at stylesheet-build time, so every theme gets consistent,
readable states without hand-tuning dozens of extra colors.
"""

import math
from dataclasses import dataclass

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QIcon,
                         QPainter, QPainterPath, QPen, QPixmap)
from PyQt6.QtWidgets import QApplication


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
def _rgb(hex_str: str):
    """'#4cc2ff' -> (76, 194, 255)"""
    h = hex_str.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def mix(a: str, b: str, t: float) -> str:
    """Blend hex colors: t=0 -> a, t=1 -> b. Returns '#rrggbb'.

    Blending toward the text color is how hover states stay readable on both
    dark themes (text is light -> surfaces lighten) and light themes (text is
    dark -> surfaces darken).
    """
    ar, ag, ab = _rgb(a)
    br, bg_, bb = _rgb(b)
    return "#%02x%02x%02x" % (round(ar + (br - ar) * t),
                              round(ag + (bg_ - ag) * t),
                              round(ab + (bb - ab) * t))


def rgba(hex_str: str, alpha: float) -> str:
    """Hex -> CSS 'rgba(r, g, b, a)' (only valid inside stylesheets)."""
    r, g, b = _rgb(hex_str)
    return f"rgba({r}, {g}, {b}, {alpha})"


# ---------------------------------------------------------------------------
# Theme definition
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    dark: bool
    # surfaces
    bg: str          # window background
    sidebar: str     # navigation sidebar
    panel: str       # card surface
    panel_2: str     # raised / hover surface
    field: str       # inputs, log console, chart inset
    border: str
    # accent + text
    accent: str
    accent_hov: str
    on_accent: str
    text: str
    dim: str
    faint: str
    # status
    success: str
    warning: str
    danger: str
    # chart series
    cpu: str
    mem: str
    down: str
    up: str


THEMES = {
    "midnight": Theme(
        "midnight", "Midnight", True,
        bg="#16161d", sidebar="#101017", panel="#1e1e27", panel_2="#282835",
        field="#13131a", border="#2c2c3a",
        accent="#4cc2ff", accent_hov="#7cd4ff", on_accent="#06222f",
        text="#f2f2f7", dim="#9d9db0", faint="#67677c",
        success="#4ade80", warning="#fbbf24", danger="#f87171",
        cpu="#4cc2ff", mem="#4ade80", down="#2dd4bf", up="#f472b6",
    ),
    "graphite": Theme(
        "graphite", "Graphite", True,
        bg="#141414", sidebar="#0e0e0e", panel="#1c1c1c", panel_2="#262626",
        field="#111111", border="#2a2a2a",
        accent="#e6b33d", accent_hov="#f0c668", on_accent="#221a05",
        text="#ededed", dim="#9c9c9c", faint="#656565",
        success="#7cc46a", warning="#f0c674", danger="#e06c5f",
        cpu="#e6b33d", mem="#7cc46a", down="#6cb6ff", up="#c99ae0",
    ),
    "nord": Theme(
        "nord", "Nord", True,
        bg="#22272f", sidebar="#1c2129", panel="#2c333f", panel_2="#39404f",
        field="#1c2129", border="#3e4656",
        accent="#88c0d0", accent_hov="#a9d6e2", on_accent="#12222a",
        text="#eceff4", dim="#a7b1c2", faint="#7b88a1",
        success="#a3be8c", warning="#ebcb8b", danger="#bf616a",
        cpu="#88c0d0", mem="#a3be8c", down="#81a1c1", up="#b48ead",
    ),
    "dracula": Theme(
        "dracula", "Dracula", True,
        bg="#242530", sidebar="#1e1f29", panel="#2c2d3a", panel_2="#383949",
        field="#1e1f28", border="#3d3e4f",
        accent="#bd93f9", accent_hov="#d3b1fa", on_accent="#1d1130",
        text="#f8f8f2", dim="#b6bad2", faint="#7d819c",
        success="#50fa7b", warning="#f1fa8c", danger="#ff5555",
        cpu="#bd93f9", mem="#50fa7b", down="#8be9fd", up="#ff79c6",
    ),
    "mocha": Theme(
        "mocha", "Mocha", True,
        bg="#1e1e2e", sidebar="#141420", panel="#262637", panel_2="#313244",
        field="#191927", border="#3a3a4e",
        accent="#cba6f7", accent_hov="#dcc7f9", on_accent="#241634",
        text="#cdd6f4", dim="#a6adc8", faint="#7f849c",
        success="#a6e3a1", warning="#f9e2af", danger="#f38ba8",
        cpu="#cba6f7", mem="#a6e3a1", down="#89dceb", up="#f5c2e7",
    ),
    "rosepine": Theme(
        "rosepine", "Rose Pine", True,
        bg="#191724", sidebar="#131120", panel="#1f1d2e", panel_2="#26233a",
        field="#15131f", border="#2b2840",
        accent="#ebbcba", accent_hov="#f4d3d0", on_accent="#2a1618",
        text="#e0def4", dim="#908caa", faint="#6e6a86",
        success="#9ccfd8", warning="#f6c177", danger="#eb6f92",
        cpu="#c4a7e7", mem="#9ccfd8", down="#56a8bf", up="#ebbcba",
    ),
    "daylight": Theme(
        "daylight", "Daylight", False,
        bg="#eef1f6", sidebar="#e6eaf2", panel="#ffffff", panel_2="#f1f4f9",
        field="#fbfcfe", border="#dde2ec",
        accent="#2563eb", accent_hov="#1d4ed8", on_accent="#ffffff",
        text="#191d27", dim="#5a6172", faint="#8a90a3",
        success="#16a34a", warning="#d97706", danger="#dc2626",
        cpu="#2563eb", mem="#16a34a", down="#0891b2", up="#db2777",
    ),
    "paper": Theme(
        "paper", "Paper", False,
        bg="#f6f2ea", sidebar="#eee8dc", panel="#fffdf8", panel_2="#f2ecdf",
        field="#fbf8f1", border="#e3dac7",
        accent="#0f766e", accent_hov="#0c615a", on_accent="#ffffff",
        text="#2b2620", dim="#6b6353", faint="#958c77",
        success="#2f7d4f", warning="#b45309", danger="#b3372f",
        cpu="#0f766e", mem="#2f7d4f", down="#4c6fb1", up="#b3567c",
    ),
}

DEFAULT_THEME = "midnight"
_active_key = DEFAULT_THEME


def active() -> Theme:
    return THEMES.get(_active_key, THEMES[DEFAULT_THEME])


def set_theme(key: str, app: QApplication = None, save_cfg: bool = True):
    """Switch the active theme. Optionally re-apply the stylesheet on `app`
    and remember the choice in the config file."""
    global _active_key
    _active_key = key if key in THEMES else DEFAULT_THEME
    if app is not None:
        app.setStyleSheet(stylesheet())
    if save_cfg:
        try:
            from sentinel import config
            cfg = config.load()
            if cfg.get("theme") != _active_key:
                cfg["theme"] = _active_key
                config.save(cfg)
        except Exception:
            pass


class _PalProxy:
    """Dynamic palette: ``Pal.ACCENT`` resolves to the ACTIVE theme's accent.

    Every existing call site keeps working unchanged - but colors are read at
    use time instead of import time, which is what makes live theme switching
    possible.
    """

    def __getattr__(self, name):
        t = active()
        try:
            return getattr(t, name.lower())
        except AttributeError:
            raise AttributeError(f"Pal has no color role {name!r}") from None

    def __repr__(self):
        return f"<active palette: {active().name}>"


Pal = _PalProxy()


# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------
_UI_STACK = ["Inter", "Segoe UI Variable", "Segoe UI", "Noto Sans",
             "Ubuntu", "DejaVu Sans"]
_MONO_STACK = ["JetBrains Mono", "Fira Code", "Cascadia Mono",
               "DejaVu Sans Mono", "Noto Sans Mono"]


def _first_available(stack):
    families = set(QFontDatabase.families())
    for name in stack:
        if name in families:
            return name
    return stack[-1]


def ui_font(point=13.0, weight=QFont.Weight.Normal):
    f = QFont(_first_available(_UI_STACK))
    f.setPointSizeF(point)
    f.setWeight(weight)
    return f


def mono_font(point=11.0):
    f = QFont(_first_available(_MONO_STACK))
    f.setPointSizeF(point)
    return f


# ---------------------------------------------------------------------------
# Global stylesheet (built from the active theme + derived shades)
# ---------------------------------------------------------------------------
def stylesheet() -> str:
    t = active()

    # ---- derived shades (work on dark AND light themes) ------------------
    btn_hov = mix(t.panel_2, t.text, 0.06)
    btn_press = mix(t.panel_2, t.text, 0.12)
    card_hov = mix(t.border, t.text, 0.10)
    input_hov = mix(t.border, t.text, 0.12)
    nav_hov = rgba(t.text, 0.05)
    nav_active = mix(t.accent, t.sidebar, 0.16)
    accent_tint = mix(t.accent, t.bg, 0.12)
    sel = rgba(t.accent, 0.20)
    sel_strong = rgba(t.accent, 0.32)
    scroll = mix(t.border, t.text, 0.10)
    scroll_hov = mix(t.border, t.text, 0.22)
    danger_bg = mix(t.danger, t.panel, 0.14)
    danger_hov = mix(t.danger, t.panel, 0.24)
    prim_dis = mix(t.accent, t.bg, 0.45)
    prim_dis_fg = mix(t.on_accent, t.bg, 0.45)
    log_text = mix(t.text, t.accent, 0.25)

    return f"""
* {{ outline: none; }}

QMainWindow, QDialog {{
    background: {t.bg};
}}

QLabel {{ background: transparent; color: {t.text}; }}

QToolTip {{
    background: {t.panel_2}; color: {t.text};
    border: 1px solid {t.border}; padding: 5px 8px; border-radius: 6px;
}}

QMenu {{
    background: {t.panel_2}; color: {t.text};
    border: 1px solid {t.border}; border-radius: 10px; padding: 6px;
}}
QMenu::item {{ padding: 6px 26px; border-radius: 6px; font-size: 13px; }}
QMenu::item:selected {{ background: {nav_hov}; }}
QMenu::separator {{
    height: 1px; background: {t.border}; margin: 5px 10px;
}}

/* ---------- cards ---------- */
QFrame#Card {{
    background: {t.panel}; border: 1px solid {t.border};
    border-radius: 14px;
}}
QFrame#Card:hover {{ border-color: {card_hov}; }}

QFrame#OptionCard {{
    background: {t.panel}; border: 1px solid {t.border};
    border-radius: 12px;
}}
QFrame#OptionCard:hover {{ border-color: {input_hov}; }}
QFrame#OptionCard[selected="true"] {{
    border: 1px solid {t.accent}; background: {accent_tint};
}}

QFrame#ListItem {{
    background: {t.field}; border: 1px solid transparent;
    border-radius: 9px;
}}
QFrame#ListItem:hover {{ border-color: {t.border}; }}

/* ---------- buttons ---------- */
QPushButton {{
    background: {t.panel_2}; color: {t.text};
    border: 1px solid transparent; border-radius: 9px;
    padding: 7px 16px; font-size: 13px;
}}
QPushButton:hover {{ background: {btn_hov}; }}
QPushButton:pressed {{ background: {btn_press}; }}
QPushButton:disabled {{ color: {t.faint}; background: {t.panel}; }}

QPushButton#Primary {{
    background: {t.accent}; color: {t.on_accent};
    font-weight: 600; padding: 9px 22px;
}}
QPushButton#Primary:hover {{ background: {t.accent_hov}; }}
QPushButton#Primary:pressed {{ background: {mix(t.accent, t.bg, 0.18)}; }}
QPushButton#Primary:disabled {{ background: {prim_dis}; color: {prim_dis_fg}; }}

QPushButton#Danger {{ background: {danger_bg}; color: {t.danger}; }}
QPushButton#Danger:hover {{ background: {danger_hov}; }}
QPushButton#Danger:disabled {{ color: {mix(t.danger, t.panel, 0.4)}; background: {t.panel}; }}

QPushButton#Ghost {{ background: transparent; color: {t.dim}; }}
QPushButton#Ghost:hover {{ background: {t.panel_2}; color: {t.text}; }}

QPushButton#IconButton {{
    background: transparent; border: none; padding: 5px;
}}
QPushButton#IconButton:hover {{
    background: {t.panel_2}; border-radius: 8px;
}}

/* sidebar navigation */
QPushButton#NavBtn {{
    background: transparent; color: {t.dim};
    border: none; border-radius: 9px;
    padding: 9px 12px; text-align: left;
    font-size: 13px; icon-size: 20px;
}}
QPushButton#NavBtn:hover {{ background: {nav_hov}; color: {t.text}; }}
QPushButton#NavBtn:checked {{
    background: {nav_active}; color: {t.text}; font-weight: 600;
}}

/* ---------- inputs ---------- */
QLineEdit {{
    background: {t.field}; color: {t.text};
    border: 1px solid {t.border}; border-radius: 9px;
    padding: 7px 10px; font-size: 13px;
    selection-background-color: {sel_strong};
}}
QLineEdit:hover {{ border-color: {input_hov}; }}
QLineEdit:focus {{ border-color: {t.accent}; }}
QLineEdit:disabled {{ color: {t.faint}; }}

QComboBox {{
    background: {t.field}; color: {t.text};
    border: 1px solid {t.border}; border-radius: 9px;
    padding: 7px 10px; font-size: 13px;
}}
QComboBox:hover {{ border-color: {input_hov}; }}
QComboBox:focus {{ border-color: {t.accent}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{
    background: {t.panel_2}; color: {t.text};
    border: 1px solid {t.border}; border-radius: 9px;
    selection-background-color: {sel};
    outline: 0; padding: 4px;
}}

QCheckBox {{ background: transparent; color: {t.text}; font-size: 13px; spacing: 8px; }}
QCheckBox::indicator {{
    width: 17px; height: 17px; border-radius: 5px;
    border: 1px solid {t.border}; background: {t.field};
}}
QCheckBox::indicator:hover {{ border-color: {t.accent}; }}
QCheckBox::indicator:checked {{
    background: {t.accent}; border-color: {t.accent};
}}
QCheckBox:disabled {{ color: {t.faint}; }}

/* ---------- tables ---------- */
QTableWidget {{
    background: transparent; border: none; color: {t.text};
    alternate-background-color: transparent; gridline-color: transparent;
    font-size: 13px;
}}
QTableWidget::item {{ padding: 5px 8px; border: none; }}
QTableWidget::item:selected {{ background: {sel}; }}
QTableWidget::item:hover {{ background: {rgba(t.text, 0.04)}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: transparent; color: {t.dim};
    border: none; border-bottom: 1px solid {t.border};
    padding: 7px 8px; font-size: 12px; font-weight: 600;
}}
QTableCornerButton::section {{ background: transparent; border: none; }}

/* ---------- tree views (restore picker) ---------- */
QTreeView {{
    background: {t.field}; color: {t.text};
    border: 1px solid {t.border}; border-radius: 9px;
    font-size: 13px; padding: 4px;
}}
QTreeView::item {{ padding: 4px 2px; border-radius: 5px; }}
QTreeView::item:hover {{ background: {rgba(t.text, 0.05)}; }}
QTreeView::item:selected {{ background: {sel}; }}
QTreeView::branch {{ background: transparent; }}
QTreeView::indicator, QTreeView::indicator:unchecked, QTreeView::indicator:checked, QTreeView::indicator:indeterminate {{
    width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid {t.border}; background: {t.bg};
}}
QTreeView::indicator:hover {{ border-color: {t.accent}; }}
QTreeView::indicator:checked {{ background: {t.accent}; border-color: {t.accent}; }}
QTreeView::indicator:indeterminate {{ background: {mix(t.accent, t.bg, 0.45)}; }}

/* ---------- progress ---------- */
QProgressBar {{
    background: {t.field}; border: 1px solid {t.border};
    border-radius: 7px; color: {t.text}; text-align: center;
    font-size: 12px; min-height: 16px; max-height: 16px;
}}
QProgressBar::chunk {{ background: {t.accent}; border-radius: 6px; }}

/* ---------- log console ---------- */
QPlainTextEdit {{
    background: {t.field}; color: {log_text};
    border: 1px solid {t.border}; border-radius: 9px;
    padding: 8px; font-size: 12px;
    selection-background-color: {sel_strong};
}}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {scroll}; border-radius: 4px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {scroll_hov}; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: {scroll}; border-radius: 4px; min-width: 28px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- scrollareas ---------- */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* ---------- dialogs ---------- */
QMessageBox {{ background: {t.panel}; }}
QMessageBox QLabel {{ color: {t.text}; font-size: 13px; }}
"""


def apply(app: QApplication, theme_key: str = None):
    """Install the design system on an application instance.

    If no theme key is given, the choice saved in the config file is used.
    """
    app.setStyle("Fusion")
    app.setFont(ui_font(13))
    key = theme_key
    if key is None:
        try:
            from sentinel import config
            key = config.load().get("theme", DEFAULT_THEME)
        except Exception:
            key = DEFAULT_THEME
    set_theme(key, app=app, save_cfg=False)


# Pre-built painting constants - creating these ONCE (instead of passing
# enum members on every paint call) keeps repeated painting cheap and avoids
# per-call enum conversion overhead.
NO_PEN = QPen(Qt.PenStyle.NoPen)
NO_BRUSH = QBrush()                     # default brush == Qt.BrushStyle.NoBrush
TRANSPARENT = QColor(0, 0, 0, 0)
ANTIALIAS = QPainter.RenderHint.Antialiasing


# ---------------------------------------------------------------------------
# Icon set - simple vector glyphs drawn with QPainter (no asset files needed).
# Icons are drawn once and cached; repeat calls are free.
# ---------------------------------------------------------------------------
_ICON_CACHE = {}


def icon(name: str, color=None, size: int = 24) -> QIcon:
    """Draw (or fetch from cache) icon `name` at `size` px.

    `color=None` uses the active theme's DIM role (resolved per call, so
    icons always match the current theme).
    """
    if color is None:
        color = Pal.DIM
    key = (name, str(color), int(size))
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached
    pm = QPixmap(size, size)
    pm.fill(TRANSPARENT)
    p = QPainter(pm)
    p.setRenderHint(ANTIALIAS)
    pen = QPen(QColor(str(color)))
    pen.setWidthF(max(1.5, size / 11.0))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(NO_BRUSH)
    _DRAW.get(name, _unknown)(p, size)
    p.end()
    result = QIcon(pm)
    _ICON_CACHE[key] = result
    return result


def _unknown(p, s):
    p.drawEllipse(QRectF(s * 0.2, s * 0.2, s * 0.6, s * 0.6))


def _dashboard(p, s):
    m, g = s * 0.16, s * 0.08
    w = (s - 2 * m - g) / 2
    for (x, y) in ((m, m), (m + w + g, m), (m, m + w + g), (m + w + g, m + w + g)):
        p.drawRoundedRect(QRectF(x, y, w, w), s * 0.09, s * 0.09)


def color_of(painter):
    """Current pen color of a painter as a QColor."""
    return painter.pen().color()


def _backup(p, s):
    # two circular arrows (sync / backup)
    c, r = QPointF(s / 2, s / 2), s * 0.32
    for (a0, a1) in ((205, 335), (25, 155)):
        rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
        p.drawArc(rect, int(a0 * 16), int((a1 - a0) * 16))
        # arrowhead at the end angle, tangent = angle + 90 deg
        rad = math.radians(a1)
        tip = QPointF(c.x() + r * math.cos(rad), c.y() - r * math.sin(rad))
        t = math.radians(a1 + 90)
        d = QPointF(math.cos(t), -math.sin(t))
        n = QPointF(-d.y(), d.x())
        L, W = s * 0.14, s * 0.085
        p.setBrush(QBrush(QColor(color_of(p))))
        path = QPainterPath()
        path.moveTo(tip + d * L)
        path.lineTo(tip - d * L * 0.15 + n * W)
        path.lineTo(tip - d * L * 0.15 - n * W)
        path.closeSubpath()
        p.drawPath(path)
        p.setBrush(NO_BRUSH)


def _processes(p, s):
    m = s * 0.18
    row = (s - 2 * m) / 2
    for i in range(3):
        y = m + i * row
        p.drawEllipse(QPointF(m + s * 0.045, y), s * 0.045, s * 0.045)
        p.drawLine(QPointF(m + s * 0.16, y), QPointF(s - m, y))


def _monitor(p, s):
    m = s * 0.14
    pts = [QPointF(m, s * 0.56), QPointF(s * 0.32, s * 0.56),
           QPointF(s * 0.42, s * 0.26), QPointF(s * 0.52, s * 0.80),
           QPointF(s * 0.62, s * 0.42), QPointF(s * 0.70, s * 0.56),
           QPointF(s - m, s * 0.56)]
    poly = QPainterPath(pts[0])
    for pt in pts[1:]:
        poly.lineTo(pt)
    p.drawPath(poly)


def _settings(p, s):
    m = s * 0.18
    for y, kx in ((s * 0.36, s * 0.62), (s * 0.68, s * 0.38)):
        p.drawLine(QPointF(m, y), QPointF(s - m, y))
        p.setBrush(QBrush(p.pen().color()))
        p.drawEllipse(QPointF(kx, y), s * 0.075, s * 0.075)
        p.setBrush(NO_BRUSH)


def _palette(p, s):
    # contrast symbol (half-filled circle) - reads as "theme / appearance"
    r = s * 0.32
    rect = QRectF(s / 2 - r, s / 2 - r, 2 * r, 2 * r)
    p.drawEllipse(rect)
    p.setBrush(QBrush(p.pen().color()))
    path = QPainterPath()
    path.moveTo(s / 2, s / 2 - r)
    path.arcTo(rect, 90, 180)
    path.closeSubpath()
    p.drawPath(path)
    p.setBrush(NO_BRUSH)


def _shield(p, s):
    m = s * 0.16
    path = QPainterPath()
    path.moveTo(s / 2, m)
    path.lineTo(s - m, s * 0.30)
    path.cubicTo(s - m, s * 0.62, s * 0.72, s * 0.82, s / 2, s - m)
    path.cubicTo(s * 0.28, s * 0.82, m, s * 0.62, m, s * 0.30)
    path.closeSubpath()
    p.drawPath(path)
    old = p.pen().widthF()
    pen = QPen(p.pen())
    pen.setWidthF(old * 1.15)
    p.setPen(pen)
    p.drawLine(QPointF(s * 0.36, s * 0.48), QPointF(s * 0.46, s * 0.58))
    p.drawLine(QPointF(s * 0.46, s * 0.58), QPointF(s * 0.66, s * 0.38))


def _folder(p, s):
    m = s * 0.16
    p.drawRoundedRect(QRectF(m, s * 0.46, s - 2 * m, s * 0.36), s * 0.07, s * 0.07)
    path = QPainterPath(QPointF(m, s * 0.46))
    path.lineTo(m, s * 0.30)
    path.lineTo(s * 0.38, s * 0.30)
    path.lineTo(s * 0.46, s * 0.38)
    path.lineTo(s - m, s * 0.38)
    path.lineTo(s - m, s * 0.46)
    p.drawPath(path)


def _drive(p, s):
    m = s * 0.16
    p.drawRoundedRect(QRectF(m, s * 0.28, s - 2 * m, s * 0.44), s * 0.09, s * 0.09)
    p.drawEllipse(QPointF(s - m - s * 0.14, s * 0.62), s * 0.035, s * 0.035)


def _plus(p, s):
    c, L = s / 2, s * 0.22
    p.drawLine(QPointF(c - L, c), QPointF(c + L, c))
    p.drawLine(QPointF(c, c - L), QPointF(c, c + L))


def _trash(p, s):
    m = s * 0.22
    p.drawLine(QPointF(m, s * 0.30), QPointF(s - m, s * 0.30))
    p.drawLine(QPointF(s * 0.38, s * 0.30), QPointF(s * 0.38, s * 0.22))
    p.drawLine(QPointF(s * 0.62, s * 0.30), QPointF(s * 0.62, s * 0.22))
    p.drawRoundedRect(QRectF(s * 0.30, s * 0.30, s * 0.40, s * 0.48), s * 0.06, s * 0.06)
    for x in (s * 0.44, s * 0.56):
        p.drawLine(QPointF(x, s * 0.40), QPointF(x, s * 0.66))


def _search(p, s):
    p.drawEllipse(QRectF(s * 0.18, s * 0.18, s * 0.44, s * 0.44))
    p.drawLine(QPointF(s * 0.56, s * 0.56), QPointF(s * 0.84, s * 0.84))


def _clock(p, s):
    r = s * 0.34
    p.drawEllipse(QRectF(s / 2 - r, s / 2 - r, 2 * r, 2 * r))
    c = QPointF(s / 2, s / 2)
    p.drawLine(c, QPointF(c.x(), c.y() - r * 0.62))
    p.drawLine(c, QPointF(c.x() + r * 0.42, c.y()))


def _check(p, s):
    p.drawLine(QPointF(s * 0.26, s * 0.52), QPointF(s * 0.44, s * 0.70))
    p.drawLine(QPointF(s * 0.44, s * 0.70), QPointF(s * 0.76, s * 0.30))


def _close(p, s):
    m = s * 0.28
    p.drawLine(QPointF(m, m), QPointF(s - m, s - m))
    p.drawLine(QPointF(s - m, m), QPointF(m, s - m))


def _arrow_up(p, s):
    c = s / 2
    p.drawLine(QPointF(c, s * 0.82), QPointF(c, s * 0.20))
    p.drawLine(QPointF(c - s * 0.17, s * 0.37), QPointF(c, s * 0.20))
    p.drawLine(QPointF(c + s * 0.17, s * 0.37), QPointF(c, s * 0.20))


def _arrow_down(p, s):
    c = s / 2
    p.drawLine(QPointF(c, s * 0.18), QPointF(c, s * 0.80))
    p.drawLine(QPointF(c - s * 0.17, s * 0.63), QPointF(c, s * 0.80))
    p.drawLine(QPointF(c + s * 0.17, s * 0.63), QPointF(c, s * 0.80))


def _play(p, s):
    p.setBrush(QBrush(p.pen().color()))
    path = QPainterPath(QPointF(s * 0.32, s * 0.22))
    path.lineTo(s * 0.80, s * 0.5)
    path.lineTo(s * 0.32, s * 0.78)
    path.closeSubpath()
    p.drawPath(path)
    p.setBrush(NO_BRUSH)


def _stop(p, s):
    p.setBrush(QBrush(p.pen().color()))
    p.drawRoundedRect(QRectF(s * 0.26, s * 0.26, s * 0.48, s * 0.48), s * 0.1, s * 0.1)
    p.setBrush(NO_BRUSH)


def _info(p, s):
    r = s * 0.34
    p.drawEllipse(QRectF(s / 2 - r, s / 2 - r, 2 * r, 2 * r))
    p.drawPoint(QPointF(s / 2, s * 0.34))
    p.drawLine(QPointF(s / 2, s * 0.48), QPointF(s / 2, s * 0.68))


def _restore(p, s):
    # arrow dropping into an open tray - reads as "bring files back"
    c = s / 2
    p.drawLine(QPointF(c, s * 0.14), QPointF(c, s * 0.50))
    p.drawLine(QPointF(c - s * 0.14, s * 0.37), QPointF(c, s * 0.50))
    p.drawLine(QPointF(c + s * 0.14, s * 0.37), QPointF(c, s * 0.50))
    m = s * 0.22
    p.drawLine(QPointF(m, s * 0.58), QPointF(m, s * 0.80))
    p.drawLine(QPointF(s - m, s * 0.58), QPointF(s - m, s * 0.80))
    p.drawLine(QPointF(m, s * 0.80), QPointF(s - m, s * 0.80))


_DRAW = {
    "dashboard": _dashboard, "backup": _backup, "processes": _processes,
    "monitor": _monitor, "settings": _settings, "shield": _shield,
    "folder": _folder, "drive": _drive, "plus": _plus, "trash": _trash,
    "search": _search, "clock": _clock, "check": _check, "close": _close,
    "arrow_up": _arrow_up, "arrow_down": _arrow_down, "play": _play,
    "stop": _stop, "info": _info, "palette": _palette, "restore": _restore,
}


def nice_ceil(x: float) -> float:
    """Round up to a nice 1/2/5 x 10^k value (for graph scaling)."""
    if x <= 0:
        return 1.0
    e = math.floor(math.log10(x))
    f = x / 10 ** e
    step = 1 if f <= 1 else 2 if f <= 2 else 5 if f <= 5 else 10
    return step * 10 ** e
