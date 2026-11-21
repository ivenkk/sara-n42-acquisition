"""FastAPI UI: file list + spectrum chart."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import AppConfig, load_config
from .n42_parser import parse_n42, sort_key_measurement_time
from .scheduler import AcquisitionScheduler
from .storage import ensure_storage_layout, instrument_dir, list_local_n42

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))


def create_app(
    config: AppConfig | None = None,
    *,
    start_scheduler: bool = True,
) -> FastAPI:
    cfg = config or load_config()
    ensure_storage_layout(cfg)
    scheduler = AcquisitionScheduler(cfg)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if start_scheduler:
            scheduler.start()
        yield
        scheduler.stop()

    app = FastAPI(
        title="SARA N42 采集与展示",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.config = cfg
    app.state.scheduler = scheduler

    static_dir = PACKAGE_DIR / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        instruments = [
            {"name": i.name, "host": i.host} for i in cfg.instruments
        ]
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {
                "instruments": instruments,
                "poll_interval_seconds": cfg.poll_interval_seconds,
                "default_host": instruments[0]["host"] if instruments else "",
            },
        )

    @app.get("/api/instruments")
    def api_instruments() -> JSONResponse:
        return JSONResponse(
            [
                {"name": i.name, "host": i.host, "port": i.port}
                for i in cfg.instruments
            ]
        )

    @app.get("/api/files")
    def api_files(host: str = Query(..., description="仪器 IP")) -> JSONResponse:
        inst = _find_instrument(cfg, host)
        if inst is None:
            raise HTTPException(status_code=404, detail=f"未知仪器: {host}")
        files = list_local_n42(cfg, inst)
        # Sort by measurement time descending
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

    @app.get("/api/spectrum")
    def api_spectrum(
        host: str = Query(...),
        filename: str = Query(...),
    ) -> JSONResponse:
        inst = _find_instrument(cfg, host)
        if inst is None:
            raise HTTPException(status_code=404, detail=f"未知仪器: {host}")
        # Prevent path traversal
        safe_name = Path(filename).name
        path = instrument_dir(cfg, inst) / safe_name
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"文件不存在: {safe_name}")
        if not cfg.matches_filename(safe_name):
            raise HTTPException(status_code=400, detail="文件不符合过滤规则")

        data = parse_n42(path)
        payload = {
            "filename": data.filename,
            "measurement_time": data.measurement_time_display,
            "measurement_time_source": data.measurement_time_source,
            "x_unit": data.x_unit,
            "x_label": data.x_label,
            "y_label": data.y_label,
            "channels": data.channels,
            "counts": data.counts,
            "error": data.error,
        }
        return JSONResponse(payload)

    @app.get("/api/status")
    def api_status() -> JSONResponse:
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


def _find_instrument(cfg: AppConfig, host: str):
    for inst in cfg.instruments:
        if inst.host == host:
            return inst
    return None
