"""`collector.run_once` 상태 판정 테스트. 네트워크 없음 — 가짜 adapter/session은 이 파일 안에만 둔다."""

from __future__ import annotations

import gzip
import logging
import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
import requests
from tenacity import wait_none

from collector import run_once
from collector.base import FetchResult
from collector.its import ItsAdapter
from collector.store import save_raw
from common.records import ObservationRecord
from common.timeutil import KST
from config.settings import Settings

NOW = datetime(2026, 11, 16, 7, 0, 40, tzinfo=KST)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(its_api_key="TESTKEY", raw_dir=str(tmp_path / "raw"))


class FakeAdapter:
    """fetch 결과를 고정하고 parse는 실제 ITS 파서를 쓰는 대역."""

    name = "its"

    def __init__(self, settings: Settings, result: FetchResult | Exception) -> None:
        self._result = result
        self._its = ItsAdapter(settings, session=None, wait=wait_none())

    def fetch(self, now: datetime) -> FetchResult:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

    def parse(self, body: bytes, collected_at: datetime) -> list[ObservationRecord]:
        return self._its.parse(body, collected_at)

    def is_auth_error(self, result: FetchResult) -> bool:
        return self._its.is_auth_error(result)


def _obs_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM traffic_observation WHERE source='its'").fetchone()[0]


def _logs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM collection_log ORDER BY id").fetchall()


def test_success_stores_records_and_raw(fixture_conn: sqlite3.Connection, settings: Settings, its_sample_xml: bytes) -> None:
    # 대상 링크를 응답에 있는 5개로 줄여 success 경로를 만든다.
    fixture_conn.execute(
        "UPDATE segment_link SET valid_to='2026-02-01T00:00:00+09:00' WHERE link_id='SYN0000000'"
    )
    adapter = FakeAdapter(settings, FetchResult(its_sample_xml, 200, None))
    result = run_once(NOW, fixture_conn, adapter, settings=settings)
    assert result.status == "success"
    assert result.links_expected == 5
    assert result.links_received == 5
    assert result.record_count == 5
    assert _obs_count(fixture_conn) == 5

    row = fixture_conn.execute(
        "SELECT * FROM traffic_observation WHERE source='its' AND link_id='SYN0000005'"
    ).fetchone()
    assert row["speed"] == 0.0
    assert row["quality_flag"] == "default_value"
    assert row["source_timestamp"] == "2026-11-16T07:00:01+09:00"
    assert row["collected_at"] == "2026-11-16T07:00:40+09:00"
    raw = Path(row["raw_file"])
    assert raw == Path(settings.raw_dir) / "its" / "20261116" / "070040.xml.gz"
    assert gzip.decompress(raw.read_bytes()) == its_sample_xml

    empty = fixture_conn.execute(
        "SELECT speed FROM traffic_observation WHERE source='its' AND link_id='SYN0000003'"
    ).fetchone()
    assert empty["speed"] is None

    logs = _logs(fixture_conn)
    assert len(logs) == 1
    assert logs[0]["status"] == "success"
    assert logs[0]["started_at"] == "2026-11-16T07:00:40+09:00"
    assert logs[0]["http_status"] == 200


def test_partial_response_logs_partial(fixture_conn: sqlite3.Connection, settings: Settings, its_partial_xml: bytes) -> None:
    adapter = FakeAdapter(settings, FetchResult(its_partial_xml, 200, None))
    result = run_once(NOW, fixture_conn, adapter, settings=settings)
    assert result.status == "partial"
    assert result.links_expected == 6
    assert result.links_received == 2
    assert result.record_count == 2
    ids = {r[0] for r in fixture_conn.execute("SELECT link_id FROM traffic_observation WHERE source='its'")}
    assert ids == {"SYN0000001", "SYN0000002"}  # 오지 않은 링크의 레코드는 만들지 않는다
    log = _logs(fixture_conn)[0]
    assert (log["status"], log["links_expected"], log["links_received"]) == ("partial", 6, 2)


def test_repeat_fetch_no_update(fixture_conn: sqlite3.Connection, settings: Settings, its_sample_xml: bytes) -> None:
    adapter = FakeAdapter(settings, FetchResult(its_sample_xml, 200, None))
    first = run_once(NOW, fixture_conn, adapter, settings=settings)
    assert first.record_count == 5
    before = _obs_count(fixture_conn)
    second = run_once(NOW.replace(minute=1), fixture_conn, adapter, settings=settings)
    assert second.status == "no_update"
    assert second.record_count == 0
    assert _obs_count(fixture_conn) == before
    assert [r["status"] for r in _logs(fixture_conn)] == ["partial", "no_update"]


def test_auth_error(fixture_conn: sqlite3.Connection, settings: Settings) -> None:
    adapter = FakeAdapter(settings, FetchResult(None, 401, "unauthorized"))
    result = run_once(NOW, fixture_conn, adapter, settings=settings)
    assert result.status == "auth_error"
    assert result.record_count == 0
    assert result.http_status == 401
    assert _obs_count(fixture_conn) == 0
    logs = _logs(fixture_conn)
    assert len(logs) == 1
    assert logs[0]["status"] == "auth_error"


def test_fetch_exception_not_raised(fixture_conn: sqlite3.Connection, settings: Settings) -> None:
    adapter = FakeAdapter(settings, RuntimeError("synthetic failure"))
    result = run_once(NOW, fixture_conn, adapter, settings=settings)
    assert result.status == "failed"
    assert result.record_count == 0
    assert "synthetic failure" in (result.error_message or "")
    assert len(_logs(fixture_conn)) == 1


def test_parse_failure_saves_raw(fixture_conn: sqlite3.Connection, settings: Settings) -> None:
    body = (
        b"<response><header><resultCode>99</resultCode><resultMsg>SYNTHETIC ERROR</resultMsg></header></response>"
    )
    adapter = FakeAdapter(settings, FetchResult(body, 200, None))
    result = run_once(NOW, fixture_conn, adapter, settings=settings)
    assert result.status == "failed"
    assert result.record_count == 0
    assert "SYNTHETIC ERROR" in (result.error_message or "")
    assert _obs_count(fixture_conn) == 0
    saved = Path(settings.raw_dir) / "its" / "20261116" / "070040.xml.gz"
    assert gzip.decompress(saved.read_bytes()) == body


_EMPTY_ITEMS = (
    b"<response><header><resultCode>0</resultCode><resultMsg>SUCCESS</resultMsg></header>"
    b"<body><totalCount>0</totalCount><items></items></body></response>"
)
_NO_LINK_ID = (
    b"<response><header><resultCode>0</resultCode><resultMsg>SUCCESS</resultMsg></header>"
    b"<body><totalCount>2</totalCount><items>"
    b"<item><speed>50.0</speed><createdDate>20261116070001</createdDate></item>"
    b"<item><linkId/><speed>40.0</speed><createdDate>20261116070001</createdDate></item>"
    b"</items></body></response>"
)


@pytest.mark.parametrize("body", [_EMPTY_ITEMS, _NO_LINK_ID], ids=["empty_items", "no_link_id"])
def test_no_readable_items_failed(fixture_conn: sqlite3.Connection, settings: Settings, body: bytes) -> None:
    adapter = FakeAdapter(settings, FetchResult(body, 200, None))
    result = run_once(NOW, fixture_conn, adapter, settings=settings)
    assert result.status == "failed"
    assert result.record_count == 0
    assert result.error_message == "응답에 읽을 수 있는 item 없음"
    log = _logs(fixture_conn)[0]
    assert (log["status"], log["error_message"]) == ("failed", "응답에 읽을 수 있는 item 없음")
    assert _obs_count(fixture_conn) == 0


def _boom(*args: object, **kwargs: object) -> object:
    raise RuntimeError("synthetic setup failure")


def test_settings_failure_not_raised(fixture_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("config.settings.get_settings", _boom)
    result = run_once(NOW, fixture_conn)
    assert result.status == "failed"
    assert "synthetic setup failure" in (result.error_message or "")
    assert _logs(fixture_conn)[0]["status"] == "failed"


def test_adapter_failure_not_raised(
    fixture_conn: sqlite3.Connection, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("collector.runner.ItsAdapter", _boom)
    result = run_once(NOW, fixture_conn, settings=settings)
    assert result.status == "failed"
    assert len(_logs(fixture_conn)) == 1


def test_setup_failure_without_conn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("config.settings.get_settings", _boom)
    result = run_once(NOW)  # DB 연결을 얻기 전에 실패 → collection_log 생략
    assert result.status == "failed"
    assert result.record_count == 0


def test_no_target_links_not_partial(fixture_conn: sqlite3.Connection, settings: Settings, its_partial_xml: bytes) -> None:
    fixture_conn.execute("DELETE FROM segment_link")
    adapter = FakeAdapter(settings, FetchResult(its_partial_xml, 200, None))
    result = run_once(NOW, fixture_conn, adapter, settings=settings)
    assert result.status == "success"
    assert result.links_expected is None
    assert _logs(fixture_conn)[0]["links_expected"] is None


def test_future_link_not_expected(fixture_conn: sqlite3.Connection, settings: Settings, its_partial_xml: bytes) -> None:
    # 아직 유효하지 않은(valid_from > now) 링크만 남기면 대상이 0개다.
    fixture_conn.execute("UPDATE segment_link SET valid_from='2027-01-01T00:00:00+09:00'")
    adapter = FakeAdapter(settings, FetchResult(its_partial_xml, 200, None))
    result = run_once(NOW, fixture_conn, adapter, settings=settings)
    assert result.links_expected is None
    assert result.status == "success"


def test_naive_now_rejected(fixture_conn: sqlite3.Connection, settings: Settings) -> None:
    adapter = FakeAdapter(settings, FetchResult(None, 401, "unauthorized"))
    with pytest.raises(ValueError):
        run_once(datetime(2026, 11, 16, 7, 0), fixture_conn, adapter, settings=settings)


class _RaisingSession:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls = 0

    def get(self, url: str, params: dict | None = None, timeout: float | None = None) -> object:
        self.calls += 1
        raise self.exc


def test_api_key_masked(
    fixture_conn: sqlite3.Connection, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    s = replace(settings, its_api_key="SECRET123", http_retries=1)
    exc = requests.ConnectionError(
        f"HTTPSConnectionPool: Max retries exceeded with url: {s.its_api_url}?apiKey=SECRET123&type=all"
    )
    session = _RaisingSession(exc)
    adapter = ItsAdapter(s, session=session, wait=wait_none())  # type: ignore[arg-type]
    result = run_once(NOW, fixture_conn, adapter, settings=s)
    assert result.status == "failed"
    assert session.calls == 2
    assert result.error_message
    assert "SECRET123" not in result.error_message
    assert "SECRET123" not in caplog.text
    stored = _logs(fixture_conn)[0]["error_message"]
    assert "SECRET123" not in stored


def test_save_raw_path(tmp_path: Path) -> None:
    p = save_raw(b"<x/>", "its", NOW, tmp_path)
    assert p == tmp_path / "its" / "20261116" / "070040.xml.gz"
    assert gzip.decompress(p.read_bytes()) == b"<x/>"
