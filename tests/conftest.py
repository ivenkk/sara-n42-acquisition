from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sara_n42.config import load_config

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def sample_config(tmp_path: Path) -> Path:
    data_root = tmp_path / "data"
    cfg = {
        "storage_root": str(data_root),
        "poll_interval_seconds": 300,
        "filename_contains": "5min",
        "file_extension": ".n42",
        "request_timeout_seconds": 20,
        "ui": {"host": "127.0.0.1", "port": 8080},
        "instruments": [
            {
                "name": "SARA-1",
                "host": "192.168.4.136",
                "port": 80,
                "username": "admin",
                "password": "admin",
            },
            {
                "name": "SARA-2",
                "host": "192.168.4.137",
                "port": 80,
                "username": "admin",
                "password": "admin",
            },
        ],
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path


@pytest.fixture
def app_config(sample_config: Path):
    return load_config(sample_config)
