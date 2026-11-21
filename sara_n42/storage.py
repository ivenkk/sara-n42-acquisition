"""Local storage helpers: per-IP directories and download log."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from .config import AppConfig, InstrumentConfig

logger = logging.getLogger(__name__)


def ensure_storage_layout(config: AppConfig) -> None:
    config.storage_root.mkdir(parents=True, exist_ok=True)
    for inst in config.instruments:
        instrument_dir(config, inst).mkdir(parents=True, exist_ok=True)


def instrument_dir(config: AppConfig, instrument: InstrumentConfig) -> Path:
    return config.storage_root / instrument.host


def list_local_n42(config: AppConfig, instrument: InstrumentConfig) -> list[Path]:
    folder = instrument_dir(config, instrument)
    if not folder.is_dir():
        return []
    files = [
        p
        for p in folder.iterdir()
        if p.is_file() and config.matches_filename(p.name)
    ]
    return files


def local_basenames(config: AppConfig, instrument: InstrumentConfig) -> set[str]:
    return {p.name for p in list_local_n42(config, instrument)}


def append_download_log(
    config: AppConfig,
    *,
    host: str,
    filename: str,
    ok: bool,
    detail: str = "",
) -> None:
    log_path = config.storage_root / "download.log"
    config.storage_root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S%z")
    status = "OK" if ok else "FAIL"
    line = f"{ts}\t{host}\t{filename}\t{status}"
    if detail:
        line += f"\t{detail}"
    line += "\n"
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line)
