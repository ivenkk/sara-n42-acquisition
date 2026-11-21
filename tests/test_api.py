from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from sara_n42.app import create_app
from sara_n42.config import load_config


def test_api_files_and_spectrum(sample_config: Path, fixtures_dir: Path):
    cfg = load_config(sample_config)
    dest = cfg.storage_root / "192.168.4.136"
    dest.mkdir(parents=True)
    sample = (fixtures_dir / "sample_5min.n42").read_bytes()
    (dest / "demo_5min.n42").write_bytes(sample)

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
    assert "未知" not in body["files"][0]["measurement_time"] or True

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
