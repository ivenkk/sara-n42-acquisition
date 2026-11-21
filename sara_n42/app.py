"""FastAPI UI: live latest spectra + search/download."""

from __future__ import annotations

import io
import logging
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import AppConfig, ConfigStore, InstrumentConfig, load_config
from .n42_parser import SpectrumData, parse_n42, sort_key_measurement_time
from .scheduler import AcquisitionScheduler
from .storage import ensure_storage_layout, find_local_n42, list_local_n42

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))


def create_app(
    config: AppConfig | None = None,
    *,
    start_scheduler: bool = True,
    watch_config: bool = True,
) -> FastAPI:
    initial = config or load_config()
    ensure_storage_layout(initial)
    store = ConfigStore(initial)
    scheduler = AcquisitionScheduler(initial)
    store.on_reload(scheduler.update_config)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if watch_config:
            store.start_watching()
        if start_scheduler:
            scheduler.start()
        yield
        scheduler.stop()
        store.stop_watching()

    app = FastAPI(
        title="SARA N42 采集与展示",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.config_store = store
    app.state.scheduler = scheduler

    def current_config() -> AppConfig:
        """Always the live config (hot-reloaded), never a startup snapshot."""
        return store.config

    # Back-compat for tests / callers that read app.state.config
    app.state.config = initial

    def _sync_state_config(new_cfg: AppConfig) -> None:
        app.state.config = new_cfg

    store.on_reload(_sync_state_config)

    static_dir = PACKAGE_DIR / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    def _page_context(*, active: str) -> dict:
        cfg = current_config()
        instruments = [
            {"name": i.name, "host": i.host} for i in cfg.instruments
        ]
        return {
            "instruments": instruments,
            "poll_interval_seconds": cfg.poll_interval_seconds,
            "default_host": instruments[0]["host"] if instruments else "",
            "active_page": active,
        }

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            _page_context(active="live"),
        )

    @app.get("/search", response_class=HTMLResponse)
    def search_page(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request,
            "search.html",
            _page_context(active="search"),
        )

    @app.get("/api/instruments")
    def api_instruments() -> JSONResponse:
        cfg = current_config()
        return JSONResponse(
            [
                {"name": i.name, "host": i.host, "port": i.port}
                for i in cfg.instruments
            ]
        )

    @app.get("/api/files")
    def api_files(host: str = Query(..., description="仪器 IP")) -> JSONResponse:
        cfg = current_config()
        inst = _find_instrument(cfg, host)
        if inst is None:
            raise HTTPException(status_code=404, detail=f"未知仪器: {host}")
        files = list_local_n42(cfg, inst)
        files_sorted = sorted(files, key=sort_key_measurement_time, reverse=True)
        items = []
        for path in files_sorted:
            meta = parse_n42(path)
            items.append(
                {
                    "filename": path.name,
                    "measurement_time": meta.measurement_time_display,
                    "measurement_time_source": meta.measurement_time_source,
                }
            )
        return JSONResponse(
            {
                "host": host,
                "name": inst.name,
                "files": items,
                "empty": len(items) == 0,
            }
        )

    @app.get("/api/spectra/latest")
    def api_spectra_latest() -> JSONResponse:
        """Latest spectrum (by measurement time) for every configured instrument.

        Always returns one entry per configured instrument. Offline instruments
        (poll failed, unreachable, or no usable local latest spectrum) have
        status "offline" and no spectrum payload for the live UI.
        """
        cfg = current_config()
        items = []
        for inst in cfg.instruments:
            latest = _latest_file(cfg, inst)
            status = _live_status(scheduler, inst.host, latest)
            if status == "offline":
                items.append(
                    {
                        "host": inst.host,
                        "name": inst.name,
                        "status": "offline",
                        "empty": True,
                        "spectrum": None,
                        "error": scheduler.last_errors.get(inst.host),
                    }
                )
                continue
            items.append(
                {
                    "host": inst.host,
                    "name": inst.name,
                    "status": "online",
                    "empty": False,
                    "spectrum": _spectrum_payload(latest),  # type: ignore[arg-type]
                    "error": None,
                }
            )
        return JSONResponse({"instruments": items})

    @app.get("/api/spectrum")
    def api_spectrum(
        host: str = Query(...),
        filename: str = Query(...),
    ) -> JSONResponse:
        cfg = current_config()
        inst = _find_instrument(cfg, host)
        if inst is None:
            raise HTTPException(status_code=404, detail=f"未知仪器: {host}")
        safe_name = Path(filename).name
        if not cfg.matches_filename(safe_name):
            raise HTTPException(status_code=400, detail="文件不符合过滤规则")
        path = find_local_n42(cfg, inst, safe_name)
        if path is None:
            raise HTTPException(status_code=404, detail=f"文件不存在: {safe_name}")
        return JSONResponse(_spectrum_payload(path))

    @app.get("/api/search")
    def api_search(
        start: str = Query(..., description="测量时间起 (ISO)"),
        end: str = Query(..., description="测量时间止 (ISO)"),
        host: str | None = Query(None, description="可选仪器 IP；空=全部"),
    ) -> JSONResponse:
        cfg = current_config()
        start_dt, end_dt = _parse_range(start, end)
        matches = _search_matches(cfg, host=host, start=start_dt, end=end_dt)
        by_host: dict[str, int] = {}
        for inst, _path, _data in matches:
            by_host[inst.host] = by_host.get(inst.host, 0) + 1
        return JSONResponse(
            {
                "count": len(matches),
                "by_host": by_host,
                "start": start_dt.isoformat(sep=" ", timespec="seconds"),
                "end": end_dt.isoformat(sep=" ", timespec="seconds"),
                "host": host,
            }
        )

    @app.get("/api/search/download")
    def api_search_download(
        start: str = Query(...),
        end: str = Query(...),
        host: str | None = Query(None),
    ) -> StreamingResponse:
        cfg = current_config()
        start_dt, end_dt = _parse_range(start, end)
        matches = _search_matches(cfg, host=host, start=start_dt, end=end_dt)
        if not matches:
            raise HTTPException(status_code=404, detail="没有符合条件的文件")

        buf = io.BytesIO()
        used_names: set[str] = set()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for inst, path, _data in matches:
                # Preserve month folder when present (data/<ip>/YYYY-MM/*.n42).
                month = path.parent.name
                if len(month) == 7 and month[4] == "-":
                    arcname = f"{inst.host}/{month}/{path.name}"
                else:
                    arcname = f"{inst.host}/{path.name}"
                if arcname in used_names:
                    # Extremely unlikely same host+name; still avoid collision.
                    arcname = f"{inst.host}/{path.stem}_{len(used_names)}{path.suffix}"
                used_names.add(arcname)
                zf.write(path, arcname=arcname)
        buf.seek(0)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"sara_n42_{stamp}.zip"
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    @app.get("/api/status")
    def api_status() -> JSONResponse:
        cfg = current_config()
        return JSONResponse(
            {
                "instruments": [i.host for i in cfg.instruments],
                "last_cycle_at": scheduler.last_cycle_at,
                "last_errors": scheduler.last_errors,
                "poll_interval_seconds": cfg.poll_interval_seconds,
            }
        )

    @app.post("/api/poll-now")
    def api_poll_now() -> JSONResponse:
        scheduler.run_once()
        return JSONResponse({"ok": True, "errors": scheduler.last_errors})

    return app


def _find_instrument(cfg: AppConfig, host: str) -> InstrumentConfig | None:
    for inst in cfg.instruments:
        if inst.host == host:
            return inst
    return None


def _latest_file(cfg: AppConfig, inst: InstrumentConfig) -> Path | None:
    files = list_local_n42(cfg, inst)
    if not files:
        return None
    return sorted(files, key=sort_key_measurement_time, reverse=True)[0]


def _live_status(
    scheduler: AcquisitionScheduler,
    host: str,
    latest: Path | None,
) -> str:
    """
    online | offline for the live spectra page.

    Prefer last-poll reachability from the scheduler when a cycle has run:
    a failed probe marks the instrument offline (stale local files are hidden).
    When no cycle has run yet, fall back to presence of a local latest spectrum.
    Reachable hosts with no usable local latest file are still offline in the UI.
    """
    reachable = scheduler.is_reachable(host)
    if reachable is False:
        return "offline"
    if latest is None:
        return "offline"
    return "online"


def _spectrum_payload(path: Path) -> dict:
    data = parse_n42(path)
    return {
        "filename": data.filename,
        "measurement_time": data.measurement_time_display,
        "measurement_time_source": data.measurement_time_source,
        "dose_rate": data.dose_rate,
        "dose_rate_unit": data.dose_rate_unit,
        "dose_rate_display": data.dose_rate_display,
        "x_unit": data.x_unit,
        "x_label": data.x_label,
        "y_label": data.y_label,
        "channels": data.channels,
        "counts": data.counts,
        "error": data.error,
    }


def _naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


def _parse_query_dt(value: str) -> datetime:
    text = (value or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="时间参数不能为空")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    candidates = [text, text.replace(" ", "T", 1)]
    for cand in candidates:
        try:
            return _naive(datetime.fromisoformat(cand))  # type: ignore[return-value]
        except ValueError:
            continue
    for fmt in (
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise HTTPException(status_code=400, detail=f"无法解析时间: {value}")


def _parse_range(start: str, end: str) -> tuple[datetime, datetime]:
    start_dt = _parse_query_dt(start)
    end_dt = _parse_query_dt(end)
    if end_dt < start_dt:
        raise HTTPException(status_code=400, detail="结束时间不能早于开始时间")
    return start_dt, end_dt


def _search_matches(
    cfg: AppConfig,
    *,
    host: str | None,
    start: datetime,
    end: datetime,
) -> list[tuple[InstrumentConfig, Path, SpectrumData]]:
    if host:
        inst = _find_instrument(cfg, host)
        if inst is None:
            raise HTTPException(status_code=404, detail=f"未知仪器: {host}")
        instruments: tuple[InstrumentConfig, ...] | list[InstrumentConfig] = (inst,)
    else:
        instruments = cfg.instruments

    matches: list[tuple[InstrumentConfig, Path, SpectrumData]] = []
    for inst in instruments:
        for path in list_local_n42(cfg, inst):
            data = parse_n42(path)
            mt = _naive(data.measurement_time)
            if mt is None:
                # Unknown measurement time cannot satisfy a time-range filter.
                continue
            if mt < start or mt > end:
                continue
            matches.append((inst, path, data))
    return matches
