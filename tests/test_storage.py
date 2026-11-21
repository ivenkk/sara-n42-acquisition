from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sara_n42.config import load_config
from sara_n42.storage import (
    find_local_n42,
    list_local_n42,
    local_basenames,
    migrate_flat_n42_files,
    place_downloaded_n42,
    resolve_month_key,
)


def test_resolve_month_from_n42_content(fixtures_dir: Path, tmp_path: Path):
    src = tmp_path / "demo_5min.n42"
    src.write_bytes((fixtures_dir / "sample_5min.n42").read_bytes())
    month, source = resolve_month_key(src)
    assert month == "2026-11"
    assert source == "measurement"


def test_resolve_month_fallback_download_time(tmp_path: Path):
    src = tmp_path / "opaque_5min.n42"
    src.write_bytes(b"not-xml")
    fixed = datetime(2026, 12, 5, 10, 0, 0)
    month, source = resolve_month_key(src, fallback_now=fixed)
    assert month == "2026-12"
    assert source == "download_time"


def test_place_and_list_month_layout(sample_config: Path, fixtures_dir: Path):
    cfg = load_config(sample_config)
    inst = cfg.instruments[0]
    staging = cfg.storage_root / "_staging"
    staging.mkdir(parents=True)
    src = staging / "demo_5min.n42"
    src.write_bytes((fixtures_dir / "sample_5min.n42").read_bytes())

    final = place_downloaded_n42(cfg, inst, src)
    assert final == cfg.storage_root / inst.host / "2026-11" / "demo_5min.n42"
    assert final.is_file()
    assert not src.exists()

    files = list_local_n42(cfg, inst)
    assert [p.name for p in files] == ["demo_5min.n42"]
    assert local_basenames(cfg, inst) == {"demo_5min.n42"}
    assert find_local_n42(cfg, inst, "demo_5min.n42") == final


def test_migrate_flat_files(sample_config: Path, fixtures_dir: Path):
    cfg = load_config(sample_config)
    host = cfg.instruments[0].host
    flat = cfg.storage_root / host
    flat.mkdir(parents=True)
    (flat / "demo_5min.n42").write_bytes(
        (fixtures_dir / "sample_5min.n42").read_bytes()
    )
    (flat / "ignore.txt").write_text("x", encoding="utf-8")

    moved = migrate_flat_n42_files(cfg)
    assert moved == 1
    assert not (flat / "demo_5min.n42").exists()
    assert (flat / "2026-11" / "demo_5min.n42").is_file()
    assert (flat / "ignore.txt").is_file()

    # Second pass is a no-op
    assert migrate_flat_n42_files(cfg) == 0
