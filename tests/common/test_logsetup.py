import logging

from common.logsetup import get_logger


def test_urllib3_debug_suppressed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    get_logger("test")
    assert logging.getLogger("urllib3").getEffectiveLevel() >= logging.WARNING
