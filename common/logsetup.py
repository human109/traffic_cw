"""공용 로거 설정. 모듈은 `get_logger(__name__)`만 사용하고 print로 운영 로그를 남기지 않는다."""

from __future__ import annotations

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_ROOT_NAME = "traffic"
_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return
    root = logging.getLogger(_ROOT_NAME)
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)

    log_dir = Path(os.environ.get("LOG_DIR", "logs"))
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            log_dir / "app.log", when="midnight", backupCount=30, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError:
        root.warning("로그 파일을 열 수 없어 stderr로만 기록한다: %s", log_dir)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """`traffic.<name>` 로거를 돌려준다. 첫 호출 때 한 번만 핸들러를 설정한다."""
    _configure()
    return logging.getLogger(f"{_ROOT_NAME}.{name}")
