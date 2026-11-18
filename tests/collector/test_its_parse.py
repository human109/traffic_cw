"""ITS 어댑터 파싱·요청 테스트. 네트워크를 호출하지 않는다 (가짜 session 사용)."""

from __future__ import annotations

from datetime import datetime

import pytest
import requests
from tenacity import wait_none

from collector.base import FetchResult
from collector.its import ItsAdapter
from common.timeutil import KST
from config.settings import Settings

COLLECTED_AT = datetime(2026, 11, 16, 7, 0, 40, tzinfo=KST)


def _xml(items: str, result_code: str = "0", result_msg: str = "SUCCESS") -> bytes:
    """synthetic: 테스트용 ITS 응답 XML 조각."""
    return (
        "<response><header>"
        f"<resultCode>{result_code}</resultCode><resultMsg>{result_msg}</resultMsg>"
        "</header><body><totalCount>1</totalCount><items>"
        f"{items}"
        "</items></body></response>"
    ).encode("utf-8")


def _item(link_id: str, speed: str) -> str:
    speed_tag = f"<speed>{speed}</speed>" if speed != "" else "<speed/>"
    return (
        f"<item><linkId>{link_id}</linkId>{speed_tag}<travelTime>10.0</travelTime>"
        "<createdDate>20261116070001</createdDate></item>"
    )


@pytest.fixture
def adapter() -> ItsAdapter:
    return ItsAdapter(Settings(its_api_key="TESTKEY"), session=None, wait=wait_none())


def test_parse_fields(adapter: ItsAdapter, its_sample_xml: bytes) -> None:
    records = adapter.parse(its_sample_xml, COLLECTED_AT)
    assert len(records) == 5
    by_id = {r.link_id: r for r in records}
    r1 = by_id["SYN0000001"]
    assert r1.source == "its"
    assert r1.source_timestamp == datetime(2026, 11, 16, 7, 0, 1, tzinfo=KST)
    assert r1.collected_at == COLLECTED_AT
    assert r1.speed == 61.0
    assert r1.travel_time == 29.5
    assert r1.volume is None
    assert r1.congestion_code is None
    assert r1.quality_flag == "ok"


def test_speed_flags(adapter: ItsAdapter, its_sample_xml: bytes) -> None:
    by_id = {r.link_id: r for r in adapter.parse(its_sample_xml, COLLECTED_AT)}
    empty = by_id["SYN0000003"]
    assert empty.speed is None
    assert empty.travel_time is None
    assert empty.quality_flag == "ok"
    zero = by_id["SYN0000005"]
    assert zero.speed == 0.0
    assert zero.quality_flag == "default_value"

    limit = Settings().max_valid_speed_kmh
    body = _xml(_item("SYN0000009", str(limit + 1)) + _item("SYN0000008", "-3") + _item("SYN0000007", str(limit)))
    flags = {r.link_id: (r.speed, r.quality_flag) for r in adapter.parse(body, COLLECTED_AT)}
    assert flags["SYN0000009"] == (limit + 1, "out_of_range")
    assert flags["SYN0000008"] == (-3.0, "out_of_range")
    assert flags["SYN0000007"] == (limit, "ok")


def test_result_code_error(adapter: ItsAdapter) -> None:
    body = _xml("", result_code="99", result_msg="SYNTHETIC ERROR")
    with pytest.raises(ValueError, match="SYNTHETIC ERROR"):
        adapter.parse(body, COLLECTED_AT)


def test_parse_not_xml_raises(adapter: ItsAdapter) -> None:
    with pytest.raises(ValueError):
        adapter.parse(b"not xml", COLLECTED_AT)


# --- fetch: 가짜 session ------------------------------------------------------


class _Resp:
    def __init__(self, status: int, content: bytes = b"") -> None:
        self.status_code = status
        self.content = content


class _FakeSession:
    """응답 또는 예외를 순서대로 돌려주는 대역. 호출 인자를 기록한다."""

    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    def get(self, url: str, params: dict | None = None, timeout: float | None = None) -> _Resp:
        self.calls.append({"url": url, "params": dict(params or {}), "timeout": timeout})
        out = self.outcomes.pop(0)
        if isinstance(out, BaseException):
            raise out
        assert isinstance(out, _Resp)
        return out


def _adapter_with(session: _FakeSession, key: str = "TESTKEY", retries: int = 3) -> ItsAdapter:
    return ItsAdapter(Settings(its_api_key=key, http_retries=retries), session=session, wait=wait_none())


def test_fetch_params(its_sample_xml: bytes) -> None:
    s = Settings()
    session = _FakeSession([_Resp(200, its_sample_xml)])
    result = _adapter_with(session).fetch(COLLECTED_AT)
    assert result == FetchResult(its_sample_xml, 200, None)
    call = session.calls[0]
    assert call["url"] == s.its_api_url
    assert call["timeout"] == s.http_timeout_s
    min_x, max_x, min_y, max_y = s.its_bbox
    assert call["params"] == {
        "apiKey": "TESTKEY",
        "type": "all",
        "drcType": "all",
        "minX": min_x,
        "maxX": max_x,
        "minY": min_y,
        "maxY": max_y,
        "getType": "xml",
    }


def test_fetch_retries_5xx_then_success(its_sample_xml: bytes) -> None:
    session = _FakeSession([_Resp(503), requests.ConnectionError("boom"), _Resp(200, its_sample_xml)])
    result = _adapter_with(session).fetch(COLLECTED_AT)
    assert result.http_status == 200
    assert result.error is None
    assert len(session.calls) == 3


def test_fetch_retries_exhausted() -> None:
    session = _FakeSession([_Resp(500)] * 3)
    result = _adapter_with(session, retries=2).fetch(COLLECTED_AT)
    assert len(session.calls) == 3  # 최초 1회 + 재시도 2회
    assert result.http_status == 500
    assert result.error is not None


@pytest.mark.parametrize("status", [401, 403])
def test_fetch_auth_not_retried(status: int) -> None:
    session = _FakeSession([_Resp(status, b"denied")])
    adapter = _adapter_with(session)
    result = adapter.fetch(COLLECTED_AT)
    assert len(session.calls) == 1
    assert result.http_status == status
    assert adapter.is_auth_error(result)


def test_default_wait_from_settings() -> None:
    adapter = ItsAdapter(Settings(http_backoff_min_s=2.0, http_backoff_max_s=7.0))
    wait = adapter._wait
    assert (wait.min, wait.max) == (2.0, 7.0)  # type: ignore[attr-defined]


def test_missing_key_is_auth_error() -> None:
    session = _FakeSession([])
    adapter = ItsAdapter(Settings(its_api_key=None), session=session, wait=wait_none())
    result = adapter.fetch(COLLECTED_AT)
    assert session.calls == []
    assert adapter.is_auth_error(result)
