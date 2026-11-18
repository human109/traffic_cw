"""ITS 국가교통정보센터 교통소통정보 어댑터 (R-02, C-02).

TODO(R-02): 요청 파라미터·응답 구조는 고시 기준 초안이다. 실호출 샘플로 다시 확인한다.
TODO(R-02): resultCode 오류 코드 목록이 확인되지 않아 인증 오류는 HTTP 401·403과 키 미설정만으로 판정한다.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

import requests
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from tenacity.wait import wait_base

from collector.base import FetchResult
from common.logsetup import get_logger
from common.records import ObservationRecord
from common.timeutil import parse_compact_kst
from config.settings import Settings

log = get_logger(__name__)

SOURCE = "its"
_AUTH_STATUSES = frozenset({401, 403})
_NO_KEY_ERROR = "ITS_API_KEY가 설정되지 않았다"
_KEY_PARAM_RE = re.compile(r"(apiKey=)[^&\s'\"]*", re.IGNORECASE)



class _ServerError(Exception):
    """5xx 응답. 재시도 대상."""

    def __init__(self, status: int, body: bytes | None) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.body = body


def mask_secret(text: str, secret: str | None) -> str:
    """문자열에서 `apiKey=...` 값과 키 문자열 자체를 `***`로 가린다."""
    masked = _KEY_PARAM_RE.sub(r"\1***", text)
    if secret:
        masked = masked.replace(secret, "***")
    return masked


def _text(item: ET.Element, tag: str) -> str | None:
    el = item.find(tag)
    if el is None or el.text is None:
        return None
    value = el.text.strip()
    return value or None


def _float_or_none(value: str | None) -> float | None:
    return None if value is None else float(value)


class ItsAdapter:
    """ITS `trafficInfo` 조회·파싱 어댑터 (`SourceAdapter` 구현)."""

    name = SOURCE

    def __init__(
        self,
        settings: Settings,
        session: requests.Session | None = None,
        wait: wait_base | None = None,
    ) -> None:
        self._settings = settings
        self._session = session
        # 재시도 대기 기본값은 설정의 지수 백오프. 테스트에서는 `wait=`로 바꿔 끼운다.
        self._wait = (
            wait
            if wait is not None
            else wait_exponential(
                multiplier=1, min=settings.http_backoff_min_s, max=settings.http_backoff_max_s
            )
        )

    # --- fetch ---------------------------------------------------------------

    def _params(self) -> dict[str, Any]:
        min_x, max_x, min_y, max_y = self._settings.its_bbox
        return {
            "apiKey": self._settings.its_api_key,
            "type": "all",
            "drcType": "all",
            "minX": min_x,
            "maxX": max_x,
            "minY": min_y,
            "maxY": max_y,
            "getType": "xml",
        }

    def _mask(self, text: str) -> str:
        return mask_secret(text, self._settings.its_api_key)

    def _log_retry(self, state: RetryCallState) -> None:
        exc = state.outcome.exception() if state.outcome else None
        log.warning("ITS 요청 재시도 %d회차: %s", state.attempt_number, self._mask(repr(exc)))

    def fetch(self, now: datetime) -> FetchResult:
        """좌표 범위로 1회 조회한다. 연결 오류·타임아웃·5xx는 지수 백오프로 `http_retries`회까지 재시도한다.

        401·403은 재시도하지 않는다. 예외 대신 `FetchResult.error`로 실패를 돌려준다.
        """
        if not self._settings.its_api_key:
            return FetchResult(None, None, _NO_KEY_ERROR)
        session = self._session if self._session is not None else requests.Session()

        def _get_once() -> Any:
            resp = session.get(
                self._settings.its_api_url, params=self._params(), timeout=self._settings.http_timeout_s
            )
            if resp.status_code >= 500:
                raise _ServerError(resp.status_code, resp.content or None)
            return resp

        retrying = Retrying(
            stop=stop_after_attempt(self._settings.http_retries + 1),
            wait=self._wait,
            retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout, _ServerError)),
            before_sleep=self._log_retry,
            reraise=True,
        )
        try:
            resp = retrying(_get_once)
        except _ServerError as e:
            return FetchResult(e.body, e.status, f"HTTP {e.status}")
        except requests.RequestException as e:
            return FetchResult(None, None, self._mask(f"{type(e).__name__}: {e}"))
        finally:
            if self._session is None:
                session.close()

        status = int(resp.status_code)
        body = resp.content or None
        if status >= 400:
            return FetchResult(body, status, f"HTTP {status}")
        return FetchResult(body, status, None)

    def is_auth_error(self, result: FetchResult) -> bool:
        """HTTP 401·403 또는 키 미설정이면 인증 오류다."""
        return result.http_status in _AUTH_STATUSES or result.error == _NO_KEY_ERROR

    # --- parse ---------------------------------------------------------------

    def _quality_flag(self, speed: float | None) -> str:
        if speed is None:
            return "ok"
        if speed == 0:
            return "default_value"
        if not math.isfinite(speed) or speed < 0 or speed > self._settings.max_valid_speed_kmh:
            return "out_of_range"
        return "ok"

    def parse(self, body: bytes, collected_at: datetime) -> list[ObservationRecord]:
        """XML 응답의 모든 item을 레코드로 만든다(대상 링크로 거르지 않는다).

        `header/resultCode`가 `0`이 아니거나 XML이 아니면 `ValueError`를 낸다.
        필수 값(linkId, createdDate)이 없거나 숫자를 읽을 수 없는 item은 건너뛰고 경고를 남긴다.
        """
        try:
            root = ET.fromstring(body)
        except ET.ParseError as e:
            raise ValueError(f"ITS 응답 XML을 읽을 수 없다: {e}") from e
        code = root.findtext("header/resultCode")
        if code is None or code.strip() != "0":
            msg = (root.findtext("header/resultMsg") or "").strip()
            raise ValueError(self._mask(f"ITS resultCode={code!r}: {msg}"))

        records: list[ObservationRecord] = []
        skipped = 0
        for item in root.findall("body/items/item"):
            try:
                link_id = _text(item, "linkId")
                created = _text(item, "createdDate")
                if link_id is None or created is None:
                    raise ValueError("linkId 또는 createdDate 없음")
                speed = _float_or_none(_text(item, "speed"))
                records.append(
                    ObservationRecord(
                        source=SOURCE,
                        link_id=link_id,
                        source_timestamp=parse_compact_kst(created),
                        collected_at=collected_at,
                        speed=speed,
                        travel_time=_float_or_none(_text(item, "travelTime")),
                        volume=None,
                        congestion_code=None,
                        quality_flag=self._quality_flag(speed),
                    )
                )
            except ValueError as e:
                skipped += 1
                log.warning("ITS item 건너뜀: %s", e)
        if skipped:
            log.warning("ITS 응답에서 읽지 못한 item %d건", skipped)
        return records
