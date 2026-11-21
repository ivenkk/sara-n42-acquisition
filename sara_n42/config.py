"""Load and validate application configuration from YAML."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Project root = parent of the sara_n42 package
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


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
