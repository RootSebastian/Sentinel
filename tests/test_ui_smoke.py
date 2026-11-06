"""UI smoke tests - the whole app, offscreen.

These catch the class of bug where a screen or a theme switch crashes at
runtime (including the "click a theme card" regression from v1.1.1).
"""

import os

import pytest

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from sentinel import history, theme

pytest.importorskip("PyQt6.QtTest")

SCREENS = ("dashboard", "backup", "history", "processes", "monitor",
           "settings")


@pytest.fixture
def win(qapp, cfg_dir, tmp_path):
    theme.set_theme(theme.DEFAULT_THEME)
    # a fake backup destination so the history screen has folders to show
    dest = tmp_path / "backup"
    (dest / "Documents").mkdir(parents=True)
    (dest / "Documents" / "hello.txt").write_text("hi")
    (dest / "Pictures").mkdir()

    from sentinel import config
    cfg = config.load()
    cfg["sources"] = [str(tmp_path / "Documents")]
    cfg["destination"] = str(dest)
    cfg["onboarded"] = True
    config.save(cfg)

    # seed a few history records
    for status, files, size in (("completed", 12, 4_000_000),
                                ("warnings", 8, 900_000),
                                ("failed", 0, 0)):
        rid = history.begin({"mode": "incremental",
                             "sources": cfg["sources"],
                             "destination": str(dest)})
        history.complete(rid, status, stats={"files": files, "bytes": size},
                         message="test record")

    from sentinel.ui.main_window import MainWindow
    w = MainWindow(demo=True)
    w.resize(1220, 780)
    w.show()
    yield w
    w.close()


def _pump(app, n=30):
    for _ in range(n):
        app.processEvents()


def test_all_screens_build_and_navigate(win, qapp):
    for key in SCREENS:
        win.go_to(key)
        _pump(qapp)
        assert win.stack.currentWidget() is win.screens[key]
    assert len(win.screens) == 6


def test_history_screen_renders_records(win, qapp):
    win.go_to("history")
    _pump(qapp)
    screen = win.screens["history"]
    assert screen.table.rowCount() == 3
    # selecting the second row populates the details card
    screen.table.selectRow(1)
    _pump(qapp)
    assert screen.detail_holder.count() > 0
    # and the folder list shows the backed-up folders
    rows = [screen.folders_holder.itemAt(i).widget()
            for i in range(screen.folders_holder.count())]
    list_items = [r for r in rows if r is not None
                  and r.objectName() == "ListItem"]
    assert len(list_items) == 2                    # Documents + Pictures


def test_restore_dialog_selection_semantics(win, qapp, tmp_path):
    from sentinel.ui.restore_dialog import RestoreDialog
    dest = str(tmp_path / "backup")
    dlg = RestoreDialog(dest, win)
    dlg.show()
    _pump(qapp, 60)
    check = int(Qt.ItemDataRole.CheckStateRole)

    docs = dlg.model.index(os.path.join(dest, "Documents"))
    dlg.model.setData(docs, Qt.CheckState.Checked.value, check)
    _pump(qapp)
    assert dlg.model.checked_paths() == [os.path.join(dest, "Documents")]

    # uncheck a file inside -> folder shows partial, file is excluded
    leaf = dlg.model.index(os.path.join(dest, "Documents", "hello.txt"))
    dlg.model.setData(leaf, Qt.CheckState.Unchecked.value, check)
    _pump(qapp)
    assert dlg.model.data(docs, check) == Qt.CheckState.PartiallyChecked
    includes, excludes = dlg.model.selection()
    assert includes == [os.path.join(dest, "Documents")]
    assert excludes == [os.path.join(dest, "Documents", "hello.txt")]
    dlg.hide()


def test_theme_card_clicks_never_crash(win, qapp):
    """Regression: clicking a theme card used to abort with
    'wrapped C/C++ object of type ThemeCard has been deleted'."""
    from sentinel.ui.settings_screen import ThemeCard
    win.go_to("settings")
    _pump(qapp)

    for key in list(theme.THEMES.keys()):
        win.go_to("settings")                     # screen rebuilt each time
        _pump(qapp)
        cards = win.screens["settings"].findChildren(ThemeCard)
        card = [c for c in cards if c.t.key == key][0]
        QTest.mouseClick(card, Qt.MouseButton.LeftButton)
        _pump(qapp, 60)
        assert theme.active().key == key, f"theme did not switch to {key}"
    # the app and all six screens survived
    assert len(win.screens) == 6
    for key in SCREENS:
        win.go_to(key)
        _pump(qapp)


def test_version_is_consistent(win):
    import sentinel
    assert sentinel.__version__ == "1.2.0"
