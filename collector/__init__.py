"""수집 모듈. 공개 진입점은 `run_once` 하나다 (C-06)."""

from collector.runner import run_once

__all__ = ["run_once"]
