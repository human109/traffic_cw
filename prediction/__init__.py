"""prediction 모듈 공개 진입점 (계약 C-06). 다른 모듈은 이 두 함수만 호출한다."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from common.timeutil import to_iso
from config.settings import get_settings
from prediction import baseline

__all__ = ["predict_latest", "backfill_actuals"]


def _require_aware(now: datetime) -> None:
    to_iso(now)  # tz 정보가 없으면 ValueError


def predict_latest(now: datetime, conn: sqlite3.Connection | None = None) -> int:
    """대상 구간별 horizon 예측을 저장하고 새로 저장한 건수를 돌려준다.

    `conn=None`이면 `database.db.connect()`로 연결하고 끝날 때 닫는다. tz 없는 `now`는 ValueError.
    """
    _require_aware(now)
    settings = get_settings()
    if conn is not None:
        return baseline.predict_all(conn, now, settings)
    from database.db import connect  # 지연 import: database 모듈과 느슨하게 결합

    own = connect()
    try:
        return baseline.predict_all(own, now, settings)
    finally:
        own.close()


def backfill_actuals(now: datetime, conn: sqlite3.Connection | None = None) -> int:
    """대상 시각이 지난 예측의 실제값·오차를 갱신하고 갱신 건수를 돌려준다.

    `conn=None`이면 `database.db.connect()`로 연결하고 끝날 때 닫는다. tz 없는 `now`는 ValueError.
    """
    _require_aware(now)
    if conn is not None:
        return baseline.backfill(conn, now)
    from database.db import connect

    own = connect()
    try:
        return baseline.backfill(own, now)
    finally:
        own.close()
