"""Backup history log tests."""

import json

from sentinel import history


def test_begin_complete_roundtrip(cfg_dir):
    cfg = {"mode": "mirror", "sources": ["/a", "/b"],
           "destination": "/dest"}
    rid = history.begin(cfg)
    history.complete(rid, "completed",
                     stats={"files": 7, "bytes": 1234},
                     message="Backup completed successfully.")

    runs = history.load()
    assert len(runs) == 1
    run = runs[0]
    assert run["id"] == rid
    assert run["status"] == "completed"
    assert run["mode"] == "mirror"
    assert run["sources"] == ["/a", "/b"]
    assert run["dest"] == "/dest"
    assert run["files"] == 7
    assert run["bytes"] == 1234
    assert run["duration_s"] is not None
    assert run["finished"] is not None


def test_newest_first(cfg_dir):
    for i in range(3):
        rid = history.begin({"sources": [f"/{i}"], "destination": "/d"})
        history.complete(rid, "completed")
    runs = history.load()
    assert [r["sources"][0] for r in runs] == ["/2", "/1", "/0"]


def test_record_is_capped(cfg_dir, monkeypatch):
    monkeypatch.setattr(history, "MAX_RECORDS", 5)
    for i in range(12):
        rid = history.begin({"sources": [f"/{i}"], "destination": "/d"})
        history.complete(rid, "completed")
    runs = history.load()
    assert len(runs) == 5
    assert runs[0]["sources"] == ["/11"]     # newest kept
    assert runs[-1]["sources"] == ["/7"]


def test_unknown_status_recorded_as_failed(cfg_dir):
    rid = history.begin({"sources": [], "destination": ""})
    history.complete(rid, "exploded")
    assert history.load()[0]["status"] == "failed"


def test_clear(cfg_dir):
    rid = history.begin({"sources": [], "destination": ""})
    history.complete(rid, "completed")
    assert history.load()
    history.clear()
    assert history.load() == []


def test_corrupt_history_is_empty_not_fatal(cfg_dir):
    (cfg_dir / "history.json").write_text("[{broken")
    assert history.load() == []
    # and writing still works afterwards
    rid = history.begin({"sources": [], "destination": ""})
    history.complete(rid, "completed")
    assert len(history.load()) == 1


def test_latest_ok(cfg_dir):
    rid = history.begin({"sources": [], "destination": "/d1"})
    history.complete(rid, "failed")
    rid = history.begin({"sources": [], "destination": "/d2"})
    history.complete(rid, "warnings")
    rid = history.begin({"sources": [], "destination": "/d3"})
    history.complete(rid, "cancelled")

    best = history.latest_ok()
    assert best["dest"] == "/d2"            # newest completed/warnings run

    history.clear()
    assert history.latest_ok() is None


def test_file_is_valid_json(cfg_dir):
    rid = history.begin({"sources": [], "destination": ""})
    history.complete(rid, "completed")
    data = json.loads((cfg_dir / "history.json").read_text())
    assert isinstance(data, list) and data[0]["id"] == rid
