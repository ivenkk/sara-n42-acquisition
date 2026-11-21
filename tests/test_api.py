from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from sara_n42.app import create_app
from sara_n42.config import load_config


def _seed_sample(cfg, fixtures_dir: Path, host: str, filename: str) -> None:
    # Fixture StartTime is 2026-11-20 → month folder 2026-11
    dest = cfg.storage_root / host / "2026-11"
    dest.mkdir(parents=True, exist_ok=True)
    sample = (fixtures_dir / "sample_5min.n42").read_bytes()
    (dest / filename).write_bytes(sample)


def test_api_files_and_spectrum(sample_config: Path, fixtures_dir: Path):
    cfg = load_config(sample_config)
    _seed_sample(cfg, fixtures_dir, "192.168.4.136", "demo_5min.n42")

    app = create_app(cfg, start_scheduler=False)
    client = TestClient(app)

    r = client.get("/api/instruments")
    assert r.status_code == 200
    assert any(i["host"] == "192.168.4.136" for i in r.json())

    r = client.get("/api/files", params={"host": "192.168.4.136"})
    assert r.status_code == 200
    body = r.json()
    assert body["empty"] is False
    assert body["files"][0]["filename"] == "demo_5min.n42"

    r = client.get(
        "/api/spectrum",
        params={"host": "192.168.4.136", "filename": "demo_5min.n42"},
    )
    assert r.status_code == 200
    spec = r.json()
    assert spec["error"] is None
    assert len(spec["counts"]) == 10
    assert spec["x_unit"] == "keV"

    r = client.get("/")
    assert r.status_code == 200
    assert "SARA N42" in r.text
    assert "实时能谱" in r.text
    assert 'id="file-list"' not in r.text

    r = client.get("/search")
    assert r.status_code == 200
    assert "检索下载" in r.text
    assert 'id="start-date"' in r.text
    assert 'id="start-time"' in r.text
    assert 'id="end-date"' in r.text
    assert 'id="end-time"' in r.text
    assert 'class="time-24h"' in r.text
    assert 'type="datetime-local"' not in r.text


def test_api_spectra_latest(sample_config: Path, fixtures_dir: Path):
    cfg = load_config(sample_config)
    _seed_sample(cfg, fixtures_dir, "192.168.4.136", "demo_5min.n42")

    app = create_app(cfg, start_scheduler=False)
    client = TestClient(app)

    r = client.get("/api/spectra/latest")
    assert r.status_code == 200
    items = r.json()["instruments"]
    assert len(items) == 2
    by_host = {i["host"]: i for i in items}
    assert by_host["192.168.4.136"]["empty"] is False
    assert by_host["192.168.4.136"]["spectrum"]["filename"] == "demo_5min.n42"
    assert by_host["192.168.4.136"]["spectrum"]["dose_rate"] == 9.550e-02
    assert by_host["192.168.4.136"]["spectrum"]["dose_rate_unit"] == "uSv/h"
    assert by_host["192.168.4.136"]["spectrum"]["dose_rate_display"] == "9.550e-02 uSv/h"
    assert by_host["192.168.4.137"]["empty"] is True


def test_api_search_count_and_zip(sample_config: Path, fixtures_dir: Path):
    cfg = load_config(sample_config)
    _seed_sample(cfg, fixtures_dir, "192.168.4.136", "demo_5min.n42")
    _seed_sample(cfg, fixtures_dir, "192.168.4.137", "other_5min.n42")

    app = create_app(cfg, start_scheduler=False)
    client = TestClient(app)

    # Fixture StartTime is 2026-11-20T12:00:00
    r = client.get(
        "/api/search",
        params={
            "start": "2026-11-20T00:00",
            "end": "2026-11-20T23:59",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert body["by_host"]["192.168.4.136"] == 1
    assert body["by_host"]["192.168.4.137"] == 1
    assert "files" not in body

    r = client.get(
        "/api/search",
        params={
            "start": "2026-11-20T00:00",
            "end": "2026-11-20T23:59",
            "host": "192.168.4.136",
        },
    )
    assert r.status_code == 200
    assert r.json()["count"] == 1

    r = client.get(
        "/api/search",
        params={
            "start": "2026-11-21T00:00",
            "end": "2026-11-21T23:59",
        },
    )
    assert r.status_code == 200
    assert r.json()["count"] == 0

    r = client.get(
        "/api/search/download",
        params={
            "start": "2026-11-20T00:00",
            "end": "2026-11-20T23:59",
            "host": "192.168.4.136",
        },
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
        assert names == ["192.168.4.136/2026-11/demo_5min.n42"]

    r = client.get(
        "/api/search/download",
        params={
            "start": "2026-11-21T00:00",
            "end": "2026-11-21T23:59",
        },
    )
    assert r.status_code == 404
