"""모듈 간에 주고받는 레코드 형식 (계약 C-02)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

CollectionStatus = Literal["success", "partial", "failed", "auth_error", "no_update"]


@dataclass(frozen=True)
class ObservationRecord:
    """링크 단위 원본 관측 1건. `traffic_observation` 1행에 대응한다."""

    source: str
    link_id: str
    source_timestamp: datetime
    collected_at: datetime
    speed: float | None
    travel_time: float | None
    volume: int | None
    congestion_code: str | None
    quality_flag: str = "ok"
    raw_file: str | None = None


@dataclass
class CollectionResult:
    """수집 1회의 결과. `collection_log` 1행에 대응한다."""

    source: str
    status: CollectionStatus
    started_at: datetime
    finished_at: datetime
    http_status: int | None
    links_expected: int | None
    links_received: int
    record_count: int
    error_message: str | None
