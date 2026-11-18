"""수집원 어댑터 공통 형식. 수집원(ITS, 경찰청 …)마다 `SourceAdapter`를 하나씩 구현한다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from common.records import ObservationRecord


@dataclass(frozen=True)
class FetchResult:
    """HTTP 요청 1회(재시도 포함)의 결과. 오류 문자열에는 인증키가 들어가지 않는다."""

    body: bytes | None
    http_status: int | None
    error: str | None


class SourceAdapter(Protocol):
    """수집원 어댑터. `run_once`는 이 인터페이스만 사용한다."""

    name: str

    def fetch(self, now: datetime) -> FetchResult:
        """원본 응답을 가져온다."""
        ...

    def parse(self, body: bytes, collected_at: datetime) -> list[ObservationRecord]:
        """원본 응답을 C-02 레코드로 바꾼다. 응답 전체가 실패면 `ValueError`."""
        ...

    def is_auth_error(self, result: FetchResult) -> bool:
        """인증 오류(키 없음·거부)인지 판정한다."""
        ...
