"""python -m sara_n42 启动采集调度 + 本机展示页。"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import uvicorn

from .config import DEFAULT_CONFIG_PATH, load_config


def _setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    # Avoid leaking credentials via urllib3 debug dumps
    logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="SARA N42 数据采集与展示系统",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="配置文件路径（默认: 程序目录下 config.yaml）",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="日志级别：INFO / ERROR / DEBUG",
    )
    parser.add_argument(
        "--no-scheduler",
        action="store_true",
        help="仅启动展示页，不启动定时下载（调试用）",
    )
    args = parser.parse_args(argv)

    _setup_logging(args.log_level)
    config = load_config(args.config)

    # Deferred import so --help works without side effects
    from .app import create_app

    app = create_app(config, start_scheduler=not args.no_scheduler)

    logging.getLogger(__name__).info(
        "展示页: http://%s:%s  （仪器数=%s）",
        config.ui.host,
        config.ui.port,
        len(config.instruments),
    )
    uvicorn.run(
        app,
        host=config.ui.host,
        port=config.ui.port,
        log_level=args.log_level.lower(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
