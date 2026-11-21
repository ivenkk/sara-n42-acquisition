from __future__ import annotations

import time
from pathlib import Path

import yaml

from sara_n42.config import ConfigStore, load_config


def test_load_config_instruments(sample_config):
    cfg = load_config(sample_config)
    assert cfg.poll_interval_seconds == 300
    assert cfg.filename_contains == "5min"
    assert cfg.ui.host == "127.0.0.1"
    assert cfg.ui.port == 8080
    assert len(cfg.instruments) == 2
    assert cfg.instruments[0].host == "192.168.4.136"


def test_matches_filename(app_config):
    assert app_config.matches_filename("abc_5min_xyz.n42")
    assert app_config.matches_filename("ABC_5MIN_XYZ.N42")
    assert not app_config.matches_filename("abc_1h_xyz.n42")
    assert not app_config.matches_filename("abc_5min_xyz.txt")


def _rewrite_config(path: Path, **overrides) -> None:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw.update(overrides)
    # Ensure mtime advances on all filesystems (incl. coarse Windows timers).
    time.sleep(0.05)
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    # Bump mtime explicitly in case write was too fast for the FS resolution.
    now = time.time()
    path.touch()
    # Some FS round mtime; force a distinct value when possible.
    try:
        import os

        os.utime(path, (now + 1, now + 1))
    except OSError:
        pass


def test_config_store_reloads_instruments(sample_config: Path):
    cfg = load_config(sample_config)
    store = ConfigStore(cfg)
    assert len(store.config.instruments) == 2

    seen: list[int] = []
    store.on_reload(lambda c: seen.append(len(c.instruments)))

    raw = yaml.safe_load(sample_config.read_text(encoding="utf-8"))
    raw["instruments"] = [
        {
            "name": "Only-One",
            "host": "192.168.4.200",
            "port": 80,
            "username": "admin",
            "password": "admin",
        }
    ]
    _rewrite_config(sample_config, instruments=raw["instruments"])

    assert store.check_and_reload() is True
    assert len(store.config.instruments) == 1
    assert store.config.instruments[0].host == "192.168.4.200"
    assert seen == [1]


def test_config_store_keeps_previous_on_invalid_yaml(sample_config: Path):
    cfg = load_config(sample_config)
    store = ConfigStore(cfg)
    before = store.config

    time.sleep(0.05)
    sample_config.write_text("instruments: [\n  - broken: true\n", encoding="utf-8")
    try:
        import os

        now = time.time()
        os.utime(sample_config, (now + 1, now + 1))
    except OSError:
        pass

    assert store.check_and_reload() is False
    assert store.config is before
    assert len(store.config.instruments) == 2
