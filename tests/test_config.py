"""Config persistence tests."""

from sentinel import config


def test_defaults_on_fresh_install(cfg_dir):
    cfg = config.load()
    assert cfg["sources"] == []
    assert cfg["destination"] == ""
    assert cfg["mode"] == "incremental"
    assert cfg["schedule"] == "manual"
    assert cfg["theme"] == "midnight"
    assert cfg["notifications"] is True
    assert cfg["onboarded"] is False


def test_save_load_roundtrip(cfg_dir):
    cfg = config.load()
    cfg["sources"] = ["/home/me/Documents"]
    cfg["destination"] = "/mnt/backup"
    cfg["mode"] = "mirror"
    config.save(cfg)

    loaded = config.load()
    assert loaded["sources"] == ["/home/me/Documents"]
    assert loaded["destination"] == "/mnt/backup"
    assert loaded["mode"] == "mirror"


def test_unknown_keys_are_dropped(cfg_dir):
    cfg = config.load()
    cfg["evil_key"] = "nope"
    config.save(cfg)
    # a hand-edited file with extra keys must not leak into the app
    loaded = config.load()
    assert "evil_key" not in loaded


def test_corrupt_file_falls_back_to_defaults(cfg_dir):
    (cfg_dir / "config.json").write_text("{not json at all")
    cfg = config.load()
    assert cfg == dict(config.DEFAULTS)
