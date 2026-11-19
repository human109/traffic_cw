"""`collector.run_once` 상태 판정 테스트. 네트워크 없음 — 가짜 adapter/session은 이 파일 안에만 둔다."""

from __future__ import annotations

import gzip
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
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
SYN_ROAD = "합성도로"


def _at(t: datetime) -> Callable[[], datetime]:
    """항상 `t`를 반환하는 시계. `run_once(..., clock=_at(NOW))`처럼 시각을 고정한다."""
    return lambda: t


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # 합성 픽스처 XML의 roadName은 "합성도로"다 (C-02 v2 저장 범위).
    return replace(
        Settings(its_api_key="TESTKEY", raw_dir=str(tmp_path / "raw")),
        its_store_road_names=(SYN_ROAD,),
    )


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
    result = run_once(NOW, fixture_conn, adapter, settings=settings, clock=_at(NOW))
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

    cols = {r[1] for r in fixture_conn.execute("PRAGMA table_info(traffic_observation)")}
    assert "road_name" not in cols  # road_name은 DB에 쓰지 않는다

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
    first = run_once(NOW, fixture_conn, adapter, settings=settings, clock=_at(NOW))
    assert first.record_count == 5
    before = _obs_count(fixture_conn)
    second = run_once(NOW.replace(minute=1), fixture_conn, adapter, settings=settings, clock=_at(NOW.replace(minute=1)))
    assert second.status == "no_update"
    assert second.record_count == 0
    assert _obs_count(fixture_conn) == before
    assert [r["status"] for r in _logs(fixture_conn)] == ["partial", "no_update"]


def test_collected_at_is_fetch_end_time(fixture_conn: sqlite3.Connection, settings: Settings, its_sample_xml: bytes) -> None:
    """I5: collected_at은 fetch가 끝난 시각이다. fetch 중 시계가 30초 진행하면 now+30초."""
    clock = [NOW]

    class _SlowAdapter(FakeAdapter):
        def fetch(self, now: datetime) -> FetchResult:
            clock[0] = clock[0] + timedelta(seconds=30)
            return super().fetch(now)

    adapter = _SlowAdapter(settings, FetchResult(its_sample_xml, 200, None))
    result = run_once(NOW, fixture_conn, adapter, settings=settings, clock=lambda: clock[0])
    row = fixture_conn.execute(
        "SELECT collected_at, raw_file FROM traffic_observation WHERE source='its' AND link_id='SYN0000001'"
    ).fetchone()
    assert row["collected_at"] == "2026-11-16T07:01:10+09:00"  # NOW + 30초
    raw = Path(row["raw_file"])
    assert raw == Path(settings.raw_dir) / "its" / "20261116" / "070110.xml.gz"  # 수신 시각 기준 경로
    # started_at은 넘겨받은 now 그대로다.
    assert result.started_at == NOW
    assert _logs(fixture_conn)[0]["started_at"] == "2026-11-16T07:00:40+09:00"


def test_naive_clock_fails_not_crashes(fixture_conn: sqlite3.Connection, settings: Settings, its_sample_xml: bytes) -> None:
    """clock이 timezone 정보 없는 datetime을 반환하면 그 회차는 failed다(예외 밖으로 새지 않음)."""
    adapter = FakeAdapter(settings, FetchResult(its_sample_xml, 200, None))
    result = run_once(
        NOW, fixture_conn, adapter, settings=settings, clock=lambda: datetime(2026, 11, 16, 7, 0, 50)
    )
    assert result.status == "failed"
    assert "timezone" in (result.error_message or "")
    assert _obs_count(fixture_conn) == 0


def test_no_update_does_not_rewrite_raw(fixture_conn: sqlite3.Connection, settings: Settings, its_sample_xml: bytes) -> None:
    """M2: 모든 레코드가 이미 저장된 회차(no_update)는 원본 파일을 새로 쓰지 않는다."""
    adapter = FakeAdapter(settings, FetchResult(its_sample_xml, 200, None))
    first = run_once(NOW, fixture_conn, adapter, settings=settings, clock=_at(NOW))
    assert first.record_count == 5
    first_raw = Path(settings.raw_dir) / "its" / "20261116" / "070040.xml.gz"
    assert first_raw.exists()

    later = NOW + timedelta(minutes=1)
    second = run_once(later, fixture_conn, adapter, settings=settings, clock=_at(later))
    assert second.status == "no_update"
    # 이번 회차(070140) 파일은 만들어지지 않고, 직전 회차 파일은 그대로다.
    assert not (Path(settings.raw_dir) / "its" / "20261116" / "070140.xml.gz").exists()
    assert first_raw.exists()
    assert gzip.decompress(first_raw.read_bytes()) == its_sample_xml


def test_no_update_keeps_previous_raw_same_second(
    fixture_conn: sqlite3.Connection, settings: Settings, its_sample_xml: bytes
) -> None:
    """M2: 같은 초에 이미 원본이 있으면(직전 회차 파일을 덮어쓴 상황) 지우지 않는다."""
    adapter = FakeAdapter(settings, FetchResult(its_sample_xml, 200, None))
    run_once(NOW, fixture_conn, adapter, settings=settings, clock=_at(NOW))
    raw = Path(settings.raw_dir) / "its" / "20261116" / "070040.xml.gz"
    before = raw.read_bytes()

    second = run_once(NOW, fixture_conn, adapter, settings=settings, clock=_at(NOW))
    assert second.status == "no_update"
    assert raw.exists()
    assert raw.read_bytes() == before


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
    result = run_once(NOW, fixture_conn, adapter, settings=settings, clock=_at(NOW))
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


def _road_xml(roads: list[tuple[str, str]]) -> bytes:
    """synthetic: (link_id, roadName) 목록으로 만든 ITS 응답."""
    items = "".join(
        f"<item><roadName> {road} </roadName><linkId>{lid}</linkId><speed>50.0</speed>"
        "<travelTime>30.0</travelTime><createdDate>20261116070001</createdDate></item>"
        for lid, road in roads
    )
    return (
        "<response><header><resultCode>0</resultCode><resultMsg>SUCCESS</resultMsg></header>"
        f"<body><totalCount>{len(roads)}</totalCount><items>{items}</items></body></response>"
    ).encode("utf-8")


def test_store_scope_only_target_road(fixture_conn: sqlite3.Connection, settings: Settings) -> None:
    roads = [
        ("SYN0000001", SYN_ROAD),
        ("SYN0000002", SYN_ROAD),
        ("SYN0000901", "다른도로"),
        ("SYN0000902", "다른도로"),
        ("SYN0000903", "다른도로"),
    ]
    body = _road_xml(roads)
    result = run_once(NOW, fixture_conn, FakeAdapter(settings, FetchResult(body, 200, None)), settings=settings, clock=_at(NOW))
    assert result.record_count == 2
    assert result.status == "partial"  # 대상 링크 6개 중 2개
    assert result.links_received == 2
    ids = {r[0] for r in fixture_conn.execute("SELECT link_id FROM traffic_observation WHERE source='its'")}
    assert ids == {"SYN0000001", "SYN0000002"}
    raw = Path(settings.raw_dir) / "its" / "20261116" / "070040.xml.gz"
    assert gzip.decompress(raw.read_bytes()) == body  # 원본은 응답 전체
    assert gzip.decompress(raw.read_bytes()).count(b"<item>") == 5


def test_no_store_road_failed(fixture_conn: sqlite3.Connection, settings: Settings) -> None:
    # 대상 링크는 도로명과 무관하게 저장되므로(M1), 도로 필터만 보려면 대상 밖 link_id를 쓴다.
    body = _road_xml([("SYN0000901", "다른도로"), ("SYN0000902", "다른도로")])
    result = run_once(NOW, fixture_conn, FakeAdapter(settings, FetchResult(body, 200, None)), settings=settings)
    assert result.status == "failed"
    assert result.record_count == 0
    assert result.error_message == "저장 대상 도로 item 없음"
    assert _obs_count(fixture_conn) == 0
    assert _logs(fixture_conn)[0]["error_message"] == "저장 대상 도로 item 없음"


def test_store_scope_keeps_target_link_from_other_road(fixture_conn: sqlite3.Connection, settings: Settings) -> None:
    """M1: 대상 링크는 도로명이 저장 대상이 아니어도 저장한다."""
    body = _road_xml([("SYN0000001", "다른도로"), ("SYN0000901", "다른도로")])
    result = run_once(
        NOW, fixture_conn, FakeAdapter(settings, FetchResult(body, 200, None)), settings=settings, clock=_at(NOW)
    )
    ids = {r[0] for r in fixture_conn.execute("SELECT link_id FROM traffic_observation WHERE source='its'")}
    assert ids == {"SYN0000001"}  # SYN0000901은 대상 링크도, 저장 대상 도로도 아니다
    assert result.record_count == 1
    assert result.status == "partial"


def test_default_store_road_excludes_fixture(fixture_conn: sqlite3.Connection, tmp_path: Path, its_sample_xml: bytes) -> None:
    # 기본 설정("창원대로")으로는 합성도로 응답을 저장하지 않는다.
    # 단 대상 링크는 도로명과 무관하게 저장되므로(M1), 대상 링크가 없는 상태에서 본다.
    fixture_conn.execute("DELETE FROM segment_link")
    s = Settings(its_api_key="TESTKEY", raw_dir=str(tmp_path / "raw"))
    result = run_once(NOW, fixture_conn, FakeAdapter(s, FetchResult(its_sample_xml, 200, None)), settings=s)
    assert result.status == "failed"
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
