"""Backup + restore engine integration tests (real rsync)."""

import filecmp
import os
import shutil

import pytest

from sentinel.backup_engine import RSYNC, run_rsync
from sentinel.restore_engine import (default_target, restore_items_from_paths,
                                     run_restore)

pytestmark = pytest.mark.skipif(RSYNC is None, reason="rsync not installed")


@pytest.fixture
def source(tmp_path):
    """A folder with a nested structure to back up."""
    src = tmp_path / "home" / "Documents"
    (src / "notes").mkdir(parents=True)
    (src / "notes" / "a.txt").write_text("hello")
    (src / "b.txt").write_text("world")
    (src.parent / "Pictures").mkdir()
    (src.parent / "Pictures" / "p.png").write_text("png")
    return src.parent            # .../home with Documents + Pictures


def _tree(root):
    out = set()
    for path, dirs, files in os.walk(root):
        rel = os.path.relpath(path, root)
        for f in files:
            out.add(os.path.join(rel, f))
    return out


# ------------------------------------------------------------------ backup --
def test_backup_copies_sources_into_dest(tmp_path, source):
    dest = str(tmp_path / "backup")
    ok, msg, stats = run_rsync([str(source / "Documents"),
                                str(source / "Pictures")], dest, "incremental")
    assert ok, msg
    assert (source / "Documents" / "b.txt").read_text() == \
        open(os.path.join(dest, "Documents", "b.txt")).read()
    assert os.path.isfile(os.path.join(dest, "Pictures", "p.png"))
    assert stats["files"] >= 3
    assert stats["bytes"] > 0


def test_incremental_only_copies_changes(tmp_path, source):
    dest = str(tmp_path / "backup")
    args = [str(source / "Documents")], dest, "incremental"
    ok, _, stats1 = run_rsync(*args)
    assert ok and stats1["files"] >= 2

    ok, _, stats2 = run_rsync(*args)          # nothing changed
    assert ok and stats2["files"] == 0

    (source / "Documents" / "b.txt").write_text("changed!")
    ok, _, stats3 = run_rsync(*args)
    assert ok and stats3["files"] == 1


def test_mirror_deletes_removed_files(tmp_path, source):
    dest = str(tmp_path / "backup")
    ok, msg, _ = run_rsync([str(source / "Documents")], dest, "mirror")
    assert ok, msg
    assert os.path.isfile(os.path.join(dest, "Documents", "b.txt"))

    os.remove(source / "Documents" / "b.txt")
    ok, msg, _ = run_rsync([str(source / "Documents")], dest, "mirror")
    assert ok, msg
    assert not os.path.exists(os.path.join(dest, "Documents", "b.txt"))


def test_backup_reports_missing_rsync_config(tmp_path):
    ok, msg, _ = run_rsync([], str(tmp_path / "d"), "incremental")
    assert not ok
    assert "No source" in msg


# ----------------------------------------------------------------- restore --
def test_restore_full_folder(tmp_path, source):
    dest = str(tmp_path / "backup")
    ok, _, _ = run_rsync([str(source / "Documents")], dest, "incremental")
    assert ok

    target = str(tmp_path / "restored")
    items = restore_items_from_paths(dest, [os.path.join(dest, "Documents")])
    ok, msg, _ = run_restore(items, target)
    assert ok, msg

    cmp = filecmp.dircmp(os.path.join(dest, "Documents"),
                         os.path.join(target, "Documents"))
    differ = cmp.diff_files + cmp.left_only + cmp.right_only
    assert not differ, differ


def test_restore_honors_exclusions(tmp_path, source):
    dest = str(tmp_path / "backup")
    run_rsync([str(source / "Documents")], dest, "incremental")

    target = str(tmp_path / "restored")
    items = restore_items_from_paths(
        dest, [os.path.join(dest, "Documents")],
        excluded=[os.path.join(dest, "Documents", "b.txt")])
    ok, msg, _ = run_restore(items, target)
    assert ok, msg
    assert os.path.isfile(os.path.join(target, "Documents", "notes", "a.txt"))
    assert not os.path.exists(os.path.join(target, "Documents", "b.txt"))


def test_restore_never_deletes_at_target(tmp_path, source):
    dest = str(tmp_path / "backup")
    run_rsync([str(source / "Documents")], dest, "incremental")

    target = tmp_path / "restored"
    target.mkdir()
    keep = target / "precious.txt"
    keep.write_text("keep me")
    # also a file that WILL be overwritten by the restore
    (target / "Documents").mkdir()
    (target / "Documents" / "b.txt").write_text("old version")

    items = restore_items_from_paths(dest, [os.path.join(dest, "Documents")])
    ok, msg, _ = run_restore(items, str(target))
    assert ok, msg
    assert keep.read_text() == "keep me"                 # untouched
    assert (target / "Documents" / "b.txt").read_text() == "world"  # updated


def test_restore_cancel(tmp_path, source):
    dest = str(tmp_path / "backup")
    run_rsync([str(source / "Documents")], dest, "incremental")
    items = restore_items_from_paths(dest, [os.path.join(dest, "Documents")])
    ok, msg, _ = run_restore(items, str(tmp_path / "r"),
                             should_cancel=lambda: True)
    assert not ok
    assert "cancel" in msg.lower()


def test_restore_empty_selection(tmp_path):
    ok, msg, _ = run_restore([], str(tmp_path / "r"))
    assert not ok
    assert "Nothing" in msg


def test_restore_items_prunes_nested_and_expands_root(tmp_path):
    root = tmp_path / "bak"
    (root / "a" / "b").mkdir(parents=True)
    (root / "c.txt").write_text("c")
    root_s = str(root)

    # nested: parent + child both checked -> only the parent remains
    items = restore_items_from_paths(root_s, [f"{root_s}/a",
                                              f"{root_s}/a/b"])
    assert [i[1] for i in items] == ["a"]

    # checking the root expands to its top-level entries
    items = restore_items_from_paths(root_s, [root_s])
    assert sorted(i[1] for i in items) == ["a", "c.txt"]


def test_default_target_is_under_home_and_stamped():
    t1 = default_target("Documents")
    assert t1.startswith(os.path.expanduser("~") + os.sep)
    assert "Sentinel restored" in t1
    assert "Documents" in t1
    assert len(t1.rsplit("-", 1)[-1]) == 6          # HHMMSS stamp
