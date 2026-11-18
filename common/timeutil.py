"""KST 시간 헬퍼. 프로젝트의 모든 시각 변환은 이 모듈을 사용한다 (AGENTS.md 6장 4).

KST는 고정 오프셋(UTC+09:00)을 쓴다. 한국은 일광절약시간이 없고, Windows에는 tz 데이터베이스가 없기 때문이다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9), name="KST")

_ISO_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


def require_aware(dt: datetime) -> None:
    """timezone 정보가 없는 datetime이면 ValueError. 진입점의 입력 검사에 쓴다."""
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"timezone 정보가 없는 datetime은 허용하지 않는다: {dt!r}")


_require_aware = require_aware


def now_kst() -> datetime:
    """현재 시각(KST)."""
    return datetime.now(KST)


def to_iso(dt: datetime) -> str:
    """KST로 변환해 `YYYY-MM-DDTHH:MM:SS+09:00` 문자열을 만든다. 초 미만은 버린다."""
    _require_aware(dt)
    return dt.astimezone(KST).replace(microsecond=0).isoformat()


def parse_iso(s: str) -> datetime:
    """ISO8601 문자열을 KST datetime으로 읽는다. 오프셋이 없으면 ValueError."""
    dt = datetime.fromisoformat(s)
    _require_aware(dt)
    return dt.astimezone(KST)


def floor_5min(dt: datetime) -> datetime:
    """KST 기준으로 5분 bin 시작 시각으로 내린다."""
    _require_aware(dt)
    k = dt.astimezone(KST)
    return k.replace(minute=k.minute - k.minute % 5, second=0, microsecond=0)


def parse_compact_kst(s: str) -> datetime:
    """`YYYYMMDDHHMMSS`(시간대 표기 없음)를 KST로 해석한다. ITS `createdDate` 형식 (R-02)."""
    if len(s) != 14 or not s.isdigit():
        raise ValueError(f"YYYYMMDDHHMMSS 형식이 아니다: {s!r}")
    return datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=KST)
