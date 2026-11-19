"""prediction 모듈 공개 진입점 (계약 C-06 v2). 다른 모듈은 이 세 함수만 호출한다."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from common.timeutil import require_aware
from config.settings import get_settings
from prediction import baseline
from prediction.evaluate import run as _run_evaluation

__all__ = ["predict_latest", "backfill_actuals", "evaluate"]


def predict_latest(now: datetime, conn: sqlite3.Connection | None = None) -> int:
    """기준 모델 3종(persistence·recent15·dow_mean)의 horizon 예측을 저장하고 저장 건수를 돌려준다.

    세 모델은 같은 base_time으로 함께 저장된다(C-04). `conn=None`이면 `database.db.connect()`로
    연결하고 끝날 때 닫는다. tz 없는 `now`는 ValueError.
    """
    require_aware(now)
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

    실제값은 `imputed`·`missing` bin에서 채우지 않고, `now − backfill_lookback_hours`보다
    이전 target은 건너뛴다(C-04). `conn=None`이면 연결해 끝날 때 닫는다. tz 없는 `now`는
    ValueError.
    """
    require_aware(now)
    settings = get_settings()
    if conn is not None:
        return baseline.backfill(conn, now, settings)
    from database.db import connect

    own = connect()
    try:
        return baseline.backfill(own, now, settings)
    finally:
        own.close()


def evaluate(now: datetime, conn: sqlite3.Connection | None = None, days: int = 7) -> int:
    """기간 `[now − days, now)`의 예측을 평가해 `model_evaluation`에 저장하고 행 수를 돌려준다 (C-04).

    대상은 실제값·예측값이 모두 있고 target_time이 평일·비공휴일·`eval_window` 안인 예측이다.
    `conn=None`이면 연결해 끝날 때 닫는다. tz 없는 `now`나 `days ≤ 0`은 ValueError.
    """
    require_aware(now)
    if days <= 0:
        raise ValueError(f"days는 양수여야 한다: {days}")
    settings = get_settings()
    if conn is not None:
        return _run_evaluation(conn, now, days, settings)
    from database.db import connect

    own = connect()
    try:
        return _run_evaluation(own, now, days, settings)
    finally:
        own.close()
