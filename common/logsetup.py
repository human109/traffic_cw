"""공용 로거 설정. 모듈은 `get_logger(__name__)`만 사용하고 print로 운영 로그를 남기지 않는다."""

from __future__ import annotations

import logging
import os
import sys
import time
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_ROOT_NAME = "traffic"
_configured = False
_ROLLOVER_RETRY_SECONDS = 3600


class SafeTimedRotatingFileHandler(TimedRotatingFileHandler):
    """자정 회전이 실패해도 로그를 잃지 않는 핸들러.

    Windows에서는 다른 프로세스가 같은 파일을 열고 있으면 회전(rename)이 실패한다.
    기본 핸들러는 그 뒤 모든 기록에서 회전을 다시 시도하다 실패해 로그가 사라진다(2026-11-23 사고).
    여기서는 실패하면 지금 파일에 계속 이어 쓰고, 한 시간 뒤에 회전을 다시 시도한다.
    """

    def doRollover(self) -> None:  # noqa: N802 (표준 라이브러리 이름)
        try:
            super().doRollover()
        except OSError as e:
            if self.stream is None:
                self.stream = self._open()
            self.rolloverAt = int(time.time()) + _ROLLOVER_RETRY_SECONDS
            sys.stderr.write(f"log rollover failed, retry in 1h: {e}\n")


def log_file_path() -> Path:
    """로그 파일 경로. `LOG_DIR`(기본 logs) / `LOG_FILE`(기본 app.log).

    한 파일은 한 프로세스만 쓴다: 상주 수집기는 app.log, 대시보드는 dashboard.log(`run_dashboard.ps1`).
    """
    return Path(os.environ.get("LOG_DIR", "logs")) / os.environ.get("LOG_FILE", "app.log")


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

    # urllib3는 DEBUG에서 요청 URL(쿼리의 API 키 포함)을 기록하므로 WARNING 미만은 막는다.
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    path = log_file_path()
    log_dir = path.parent
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = SafeTimedRotatingFileHandler(
            path, when="midnight", backupCount=30, encoding="utf-8"
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
