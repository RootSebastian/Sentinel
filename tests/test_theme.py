"""Design system tests."""

import pytest

from sentinel import theme


def test_eight_themes_ship():
    assert len(theme.THEMES) == 8
    assert sum(1 for t in theme.THEMES.values() if t.dark) == 6
    assert sum(1 for t in theme.THEMES.values() if not t.dark) == 2


def test_every_theme_is_complete():
    for key, t in theme.THEMES.items():
        for field in theme.Theme.__dataclass_fields__:
            value = getattr(t, field)
            if isinstance(value, bool):
                continue                     # dark=False is fine
            assert value, f"{key}.{field} is empty"
        # a light theme needs dark=False and vice versa
        channels = (int(t.bg[1:3], 16) + int(t.bg[3:5], 16)
                    + int(t.bg[5:7], 16))
        assert t.dark == (channels < 200), f"{key}: bg does not match dark flag"


def test_set_theme_switches_active_and_stylesheet():
    for key in theme.THEMES:
        theme.set_theme(key)
        assert theme.active().key == key
        qss = theme.stylesheet()
        assert theme.active().accent.lower().lstrip("#") in \
            qss.lower().replace("#", "")
    theme.set_theme(theme.DEFAULT_THEME)


def test_pal_resolves_active_theme(qapp):
    theme.set_theme("dracula")
    assert theme.Pal.ACCENT == theme.THEMES["dracula"].accent
    theme.set_theme("paper")
    assert theme.Pal.ACCENT == theme.THEMES["paper"].accent
    theme.set_theme(theme.DEFAULT_THEME)


def test_mix_blends(qapp):
    mid = theme.mix("#000000", "#ffffff", 0.5)
    assert mid in ("#7f7f7f", "#808080")   # rounding may go either way
    assert theme.mix("#123456", "#123456", 0.73) == "#123456"


def test_icon_set_has_all_nav_glyphs(qapp):
    for name in ("dashboard", "backup", "processes", "monitor", "settings",
                 "clock", "restore", "shield", "folder", "search"):
        assert not theme.icon(name, "#ffffff", 24).isNull()
