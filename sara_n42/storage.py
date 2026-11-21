"""Local storage helpers: per-IP / per-month directories and download log."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from .config import AppConfig, InstrumentConfig
from .n42_parser import measurement_time_from_filename, parse_n42

logger = logging.getLogger(__name__)


def ensure_storage_layout(config: AppConfig) -> None:
    config.storage_root.mkdir(parents=True, exist_ok=True)
    for inst in config.instruments:
        instrument_dir(config, inst).mkdir(parents=True, exist_ok=True)
    migrated = migrate_flat_n42_files(config)
    if migrated:
        logger.info("已将 %s 个扁平 .n42 迁移到 YYYY-MM 子目录", migrated)


def instrument_dir(config: AppConfig, instrument: InstrumentConfig) -> Path:
    return config.storage_root / instrument.host


def month_key(dt: datetime) -> str:
    """Return ``YYYY-MM`` from a measurement or fallback timestamp."""
    if dt.tzinfo is not None:
        # Keep calendar components of the aware timestamp (UTC Z → UTC month).
        return dt.strftime("%Y-%m")
    return dt.strftime("%Y-%m")


def fallback_month_now() -> datetime:
    """Local timezone clock used when measurement month is unknown."""
    return datetime.now(timezone.utc).astimezone()


def resolve_month_key(
    path: Path,
    *,
    filename: str | None = None,
    fallback_now: datetime | None = None,
) -> tuple[str, str]:
    """
    Decide ``YYYY-MM`` for a file.

    Priority: N42 content → filename timestamp → download/local time.
    Returns ``(month_key, source)`` where source is
    ``measurement`` | ``filename`` | ``download_time``.
    """
    name = filename or path.name
    data = parse_n42(path)
    if data.measurement_time is not None:
        if data.measurement_time_source == "n42":
            return month_key(data.measurement_time), "measurement"
        if data.measurement_time_source == "filename":
            return month_key(data.measurement_time), "filename"
        return month_key(data.measurement_time), "measurement"

    mt = measurement_time_from_filename(name)
    if mt is not None:
        return month_key(mt), "filename"

    now = fallback_now or fallback_month_now()
    return month_key(now), "download_time"


def month_dir(
    config: AppConfig,
    instrument: InstrumentConfig,
    yyyy_mm: str,
) -> Path:
    return instrument_dir(config, instrument) / yyyy_mm


def list_local_n42(config: AppConfig, instrument: InstrumentConfig) -> list[Path]:
    """All matching .n42 files under the instrument tree (month folders)."""
    folder = instrument_dir(config, instrument)
    if not folder.is_dir():
        return []
    files: list[Path] = []
    for p in folder.rglob("*"):
        if p.is_file() and config.matches_filename(p.name):
            files.append(p)
    return files


def find_local_n42(
    config: AppConfig,
    instrument: InstrumentConfig,
    filename: str,
) -> Path | None:
    """Locate a file by basename anywhere under the instrument month layout."""
    safe = Path(filename).name
    for path in list_local_n42(config, instrument):
        if path.name == safe:
            return path
    return None


def local_basenames(config: AppConfig, instrument: InstrumentConfig) -> set[str]:
    return {p.name for p in list_local_n42(config, instrument)}


def place_n42_file(
    host_dir: Path,
    src: Path,
    *,
    fallback_now: datetime | None = None,
) -> Path:
    """
    Move ``src`` into ``host_dir/YYYY-MM/`` based on measurement month.

    Never overwrites an existing target; deletes the staging file if the
    destination already exists.
    """
    yyyy_mm, source = resolve_month_key(src, fallback_now=fallback_now)
    dest_dir = host_dir / yyyy_mm
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if dest.resolve() == src.resolve():
        return dest
    if dest.exists():
        logger.info(
            "目标已存在，跳过迁移/落盘 %s → %s (month via %s)",
            src.name,
            dest,
            source,
        )
        if src.exists() and src.resolve() != dest.resolve():
            src.unlink(missing_ok=True)
        return dest
    src.replace(dest)
    logger.debug("落盘 %s → %s (month via %s)", src.name, dest, source)
    return dest


def place_downloaded_n42(
    config: AppConfig,
    instrument: InstrumentConfig,
    src: Path,
    *,
    fallback_now: datetime | None = None,
) -> Path:
    return place_n42_file(
        instrument_dir(config, instrument),
        src,
        fallback_now=fallback_now,
    )


def migrate_flat_n42_files(config: AppConfig) -> int:
    """
    Move matching .n42 files that sit directly under ``data/<ip>/`` into
    ``data/<ip>/YYYY-MM/``. Already-nested month folders are left alone.
    """
    root = config.storage_root
    if not root.is_dir():
        return 0

    moved = 0
    for host_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for path in sorted(host_dir.iterdir()):
            if not path.is_file():
                continue
            if not config.matches_filename(path.name):
                continue
            # File is flat under the host dir (not already in YYYY-MM/).
            final = place_n42_file(host_dir, path)
            if final.parent != host_dir:
                moved += 1
    return moved


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
