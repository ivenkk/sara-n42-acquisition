"""Background poll loop: list → filter → incremental download per instrument."""

from __future__ import annotations

import logging
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from .config import AppConfig
from .soap_client import SaraSoapClient, SaraSoapError
from .storage import (
    append_download_log,
    ensure_storage_layout,
    local_basenames,
    place_downloaded_n42,
)

logger = logging.getLogger(__name__)


class AcquisitionScheduler:
    """
    Start-immediate, then every poll_interval_seconds.

    One instrument failure never stops the rest of the round or the loop.
    """

    def __init__(
        self,
        config: AppConfig,
        *,
        client_factory: Callable[..., SaraSoapClient] | None = None,
    ) -> None:
        self._config_lock = threading.RLock()
        self.config = config
        self._client_factory = client_factory or (
            lambda inst: SaraSoapClient(
                inst, timeout=self.config.request_timeout_seconds
            )
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.last_cycle_at: float | None = None
        self.last_errors: dict[str, str] = {}
        # Hosts that completed the last poll cycle without error.
        self.last_ok_hosts: set[str] = set()

    def update_config(self, config: AppConfig) -> None:
        """Apply a hot-reloaded config; subsequent polls use the new instrument list."""
        with self._config_lock:
            self.config = config
        ensure_storage_layout(config)
        logger.info(
            "调度器已切换到新配置：仪器数=%s，轮询间隔=%ss",
            len(config.instruments),
            config.poll_interval_seconds,
        )

    def is_reachable(self, host: str) -> bool | None:
        """
        Last-poll reachability for an instrument host.

        Returns True/False after at least one cycle; None if never polled yet.
        """
        if self.last_cycle_at is None:
            return None
        return host in self.last_ok_hosts and host not in self.last_errors

    def start(self) -> None:
        ensure_storage_layout(self.config)
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="sara-n42-poller",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "调度已启动：立即执行一轮，之后每 %s 秒轮询",
            self.config.poll_interval_seconds,
        )

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def run_once(self) -> None:
        """Public entry for tests / manual trigger."""
        self._cycle()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._cycle()
            except Exception:  # noqa: BLE001 — never kill the loop
                logger.exception("轮询周期发生未捕获异常，将继续下一轮")
            # Wait interruptibly; interval comes from the live (possibly reloaded) config.
            with self._config_lock:
                interval = self.config.poll_interval_seconds
            self._stop.wait(interval)

    def _cycle(self) -> None:
        with self._lock:
            with self._config_lock:
                cfg = self.config
            logger.info(
                "开始一轮检查，仪器数=%s",
                len(cfg.instruments),
            )
            errors: dict[str, str] = {}
            ok_hosts: set[str] = set()
            for inst in cfg.instruments:
                try:
                    self._process_instrument(inst, cfg)
                    ok_hosts.add(inst.host)
                except Exception as exc:  # noqa: BLE001
                    msg = str(exc)
                    errors[inst.host] = msg
                    logger.error(
                        "仪器 %s (%s) 处理失败: %s",
                        inst.name,
                        inst.host,
                        msg,
                    )
                    append_download_log(
                        cfg,
                        host=inst.host,
                        filename="*",
                        ok=False,
                        detail=msg,
                    )
            self.last_errors = errors
            self.last_ok_hosts = ok_hosts
            self.last_cycle_at = time.time()
            logger.info("本轮检查结束")

    def _process_instrument(self, inst, cfg: AppConfig | None = None) -> None:
        config = cfg if cfg is not None else self.config
        client = self._client_factory(inst)
        try:
            remote_names = client.get_file_names(
                file_type=config.file_extension
            )
        except SaraSoapError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SaraSoapError(f"列出文件失败: {exc}") from exc

        filtered = [
            name
            for name in remote_names
            if config.matches_filename(name)
        ]
        existing = local_basenames(config, inst)
        todo = [name for name in filtered if name not in existing]

        logger.info(
            "%s (%s): 远程匹配 %s 个，待下载 %s 个",
            inst.name,
            inst.host,
            len(filtered),
            len(todo),
        )
        if not todo:
            return

        # Stage into a temp dir, then move each file into data/<ip>/YYYY-MM/.
        with tempfile.TemporaryDirectory(prefix="sara_n42_dl_") as tmp:
            staging = Path(tmp)
            try:
                saved = client.download_files(todo, staging)
            except SaraSoapError as exc:
                append_download_log(
                    config,
                    host=inst.host,
                    filename=",".join(todo),
                    ok=False,
                    detail=str(exc),
                )
                raise

            placed_by_name: dict[str, Path] = {}
            for staged in saved:
                final = place_downloaded_n42(config, inst, staged)
                placed_by_name[final.name] = final

        existing_after = local_basenames(config, inst)
        for name in todo:
            if name in placed_by_name:
                final = placed_by_name[name]
                append_download_log(
                    config, host=inst.host, filename=name, ok=True
                )
                logger.info("已保存 %s → %s", name, final)
            elif name in existing_after:
                logger.info("文件已存在，跳过 %s", name)
            else:
                append_download_log(
                    config,
                    host=inst.host,
                    filename=name,
                    ok=False,
                    detail="包中未找到该文件",
                )
                logger.error(
                    "下载包中未找到 %s @ %s", name, inst.host
                )
