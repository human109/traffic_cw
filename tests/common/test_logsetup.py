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
