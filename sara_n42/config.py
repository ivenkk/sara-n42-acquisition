"""Load and validate application configuration from YAML."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger(__name__)

# Project root = parent of the sara_n42 package
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
# How often the watcher polls config mtime (Windows-friendly; no watchdog required).
DEFAULT_RELOAD_POLL_SECONDS = 2.0


@dataclass(frozen=True)
class InstrumentConfig:
    name: str
    host: str
    port: int = 80
    username: str = "admin"
    password: str = "admin"

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass(frozen=True)
class UIConfig:
    host: str = "127.0.0.1"
    port: int = 8080


@dataclass(frozen=True)
class AppConfig:
    storage_root: Path
    poll_interval_seconds: int = 300
    filename_contains: str = "5min"
    file_extension: str = ".n42"
    request_timeout_seconds: float = 20.0
    ui: UIConfig = field(default_factory=UIConfig)
    instruments: tuple[InstrumentConfig, ...] = ()
    config_path: Path = DEFAULT_CONFIG_PATH

    def matches_filename(self, name: str) -> bool:
        lower = name.lower()
        ext = self.file_extension.lower()
        needle = self.filename_contains.lower()
        return lower.endswith(ext) and needle in lower


def _as_path(value: str | Path, base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base / path).resolve()
    return path


def load_config(path: Path | str | None = None) -> AppConfig:
    """Load YAML config. Relative paths resolve against the project root."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise FileNotFoundError(
            f"找不到配置文件: {config_path}\n"
            "请复制 config.example.yaml 为 config.yaml 并填写仪器信息。"
        )

    with config_path.open("r", encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    base = config_path.parent.resolve()
    ui_raw = raw.get("ui") or {}
    instruments_raw = raw.get("instruments") or []

    instruments: list[InstrumentConfig] = []
    for item in instruments_raw:
        if not isinstance(item, dict):
            raise ValueError("instruments 列表中的每一项必须是映射对象")
        host = str(item.get("host", "")).strip()
        if not host:
            raise ValueError("仪器配置缺少 host")
        instruments.append(
            InstrumentConfig(
                name=str(item.get("name") or host),
                host=host,
                port=int(item.get("port", 80)),
                username=str(item.get("username", "admin")),
                password=str(item.get("password", "")),
            )
        )

    timeout = float(raw.get("request_timeout_seconds", 20))
    if timeout < 15 or timeout > 30:
        # Keep within the recommended band but allow exact bounds.
        timeout = max(15.0, min(30.0, timeout))

    return AppConfig(
        storage_root=_as_path(raw.get("storage_root", "./data"), base),
        poll_interval_seconds=int(raw.get("poll_interval_seconds", 300)),
        filename_contains=str(raw.get("filename_contains", "5min")),
        file_extension=str(raw.get("file_extension", ".n42")),
        request_timeout_seconds=timeout,
        ui=UIConfig(
            host=str(ui_raw.get("host", "127.0.0.1")),
            port=int(ui_raw.get("port", 8080)),
        ),
        instruments=tuple(instruments),
        config_path=config_path.resolve(),
    )


def _file_mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


class ConfigStore:
    """
    Thread-safe holder for the live AppConfig.

    Polls ``config_path`` mtime on a background thread (default every 2s).
    On change, reloads YAML; invalid YAML keeps the previous config and logs ERROR.
    Listeners are notified after a successful reload.
    """

    def __init__(
        self,
        config: AppConfig,
        *,
        poll_seconds: float = DEFAULT_RELOAD_POLL_SECONDS,
    ) -> None:
        self._lock = threading.RLock()
        self._config = config
        self._path = config.config_path
        self._mtime = _file_mtime(self._path)
        self._poll_seconds = max(0.5, float(poll_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._listeners: list[Callable[[AppConfig], None]] = []

    @property
    def config(self) -> AppConfig:
        with self._lock:
            return self._config

    @property
    def path(self) -> Path:
        return self._path

    def on_reload(self, callback: Callable[[AppConfig], None]) -> None:
        """Register a callback invoked with the new config after a successful reload."""
        self._listeners.append(callback)

    def start_watching(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._watch_loop,
            name="sara-n42-config-watch",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "配置热加载已启动：监视 %s（每 %.1f 秒）",
            self._path,
            self._poll_seconds,
        )

    def stop_watching(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    def check_and_reload(self) -> bool:
        """
        If the config file mtime changed, attempt reload.

        Returns True when a new config was applied; False otherwise
        (unchanged, missing, or invalid YAML kept previous).
        """
        mtime = _file_mtime(self._path)
        with self._lock:
            prev_mtime = self._mtime
        if mtime is None:
            # File temporarily missing (editor rename/replace) — wait.
            return False
        if prev_mtime is not None and mtime == prev_mtime:
            return False

        try:
            new_cfg = load_config(self._path)
        except Exception as exc:  # noqa: BLE001 — keep previous on any parse/IO error
            logger.error(
                "配置热加载失败，保留上一份有效配置 (%s): %s",
                self._path,
                exc,
            )
            # Advance mtime so we do not spam the same bad file every poll.
            with self._lock:
                self._mtime = mtime
            return False

        with self._lock:
            old = self._config
            self._config = new_cfg
            self._mtime = mtime
            listeners = list(self._listeners)

        logger.info(
            "已热加载配置：仪器数 %s → %s，poll_interval=%ss",
            len(old.instruments),
            len(new_cfg.instruments),
            new_cfg.poll_interval_seconds,
        )
        for cb in listeners:
            try:
                cb(new_cfg)
            except Exception:  # noqa: BLE001
                logger.exception("配置热加载回调失败")
        return True

    def _watch_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.check_and_reload()
            except Exception:  # noqa: BLE001 — never kill the watcher
                logger.exception("配置监视循环异常，将继续")
            self._stop.wait(self._poll_seconds)
            # Tiny yield so tight unit tests can interleave without busy-spin.
            time.sleep(0)
