import logging

from common.logsetup import get_logger


def test_urllib3_debug_suppressed() -> None:
    get_logger("test")
    assert logging.getLogger("urllib3").getEffectiveLevel() >= logging.WARNING


def test_tests_do_not_write_operational_log() -> None:
    from pathlib import Path

    get_logger("test")
    files = [
        Path(h.baseFilename).resolve()
        for h in logging.getLogger("traffic").handlers
        if isinstance(h, logging.FileHandler)
    ]
    repo_logs = (Path(__file__).resolve().parents[2] / "logs").resolve()
    assert files, "파일 핸들러가 있어야 한다"
    assert all(repo_logs not in f.parents for f in files)


def _record(msg: str) -> logging.LogRecord:
    return logging.LogRecord("traffic.t", logging.INFO, __file__, 1, msg, None, None)


def test_rollover_failure_keeps_logging(tmp_path) -> None:
    """다른 프로세스가 파일을 잡고 있어 회전(rename)이 실패해도 로그를 잃지 않는다 (2026-11-23 사고)."""
    from common.logsetup import SafeTimedRotatingFileHandler

    path = tmp_path / "app.log"
    h = SafeTimedRotatingFileHandler(path, when="midnight", encoding="utf-8")
    try:
        h.emit(_record("before"))

        def _locked(src: str, dst: str) -> None:
            raise PermissionError(32, "file is being used by another process")

        h.rotate = _locked  # type: ignore[method-assign]
        h.rolloverAt = 0  # 자정이 지난 것처럼
        h.emit(_record("after-1"))
        h.emit(_record("after-2"))
        h.flush()
        text = path.read_text(encoding="utf-8")
        assert "before" in text and "after-1" in text and "after-2" in text
        assert h.rolloverAt > 0  # 매 기록마다 회전을 재시도하지 않는다
    finally:
        h.close()


def test_log_file_name_from_env(tmp_path, monkeypatch) -> None:
    """LOG_FILE로 파일 이름을 바꿀 수 있다 (대시보드는 dashboard.log를 쓴다)."""
    from common.logsetup import log_file_path

    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_FILE", "dashboard.log")
    assert log_file_path() == tmp_path / "dashboard.log"
    monkeypatch.delenv("LOG_FILE")
    assert log_file_path() == tmp_path / "app.log"
