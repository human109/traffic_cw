"""synthetic: prediction 테스트 공용 헬퍼. 실제 교통 데이터가 아니며 운영 DB에 쓰지 않는다.

`segment_traffic_5min`·`traffic_prediction` 행은 테스트가 직접 넣는 합성 값이다.
여기서 만든 수치를 실제 성능으로 보고하지 않는다 (AGENTS.md 6장 1).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from common.timeutil import KST, to_iso
from prediction.baseline import DOW_MEAN_VERSION, PERSISTENCE_VERSION, RECENT15_VERSION

BIN = timedelta(minutes=5)


def t(day: int, hour: int, minute: int, second: int = 0, month: int = 11) -> datetime:
    """2026년 11월(기본)의 KST 시각. 과거 주차 데이터는 `month=10`으로 만든다."""
    return datetime(2026, month, day, hour, minute, second, tzinfo=KST)


def insert_bin(
    conn: sqlite3.Connection,
    segment_id: str,
    bin_time: datetime,
    speed: float | None,
    *,
    available_at: datetime | None = None,
    flag: str = "ok",
    is_imputed: int = 0,
) -> None:
    """`segment_traffic_5min`에 합성 bin 1개를 넣는다. available_at 기본값은 bin 끝."""
    available = available_at if available_at is not None else bin_time + BIN
    conn.execute(
        "INSERT OR REPLACE INTO segment_traffic_5min"
        " (segment_id, bin_time, available_at, speed, n_links_expected, n_links_observed,"
        "  is_imputed, quality_flag, processed_at)"
        " VALUES (?, ?, ?, ?, 2, 2, ?, ?, ?)",
        (
            segment_id,
            to_iso(bin_time),
            to_iso(available),
            speed,
            is_imputed,
            flag,
            to_iso(available),
        ),
    )
    conn.commit()


def ensure_registry(conn: sqlite3.Connection, trained_at: datetime) -> None:
    """기준 모델 3종을 `model_registry`에 등록한다(FK 충족용)."""
    conn.executemany(
        "INSERT OR IGNORE INTO model_registry"
        " (model_version, model_type, target_var, horizon, trained_at, is_active)"
        " VALUES (?, ?, 'speed', 0, ?, 1)",
        [
            (PERSISTENCE_VERSION, "baseline_persistence", to_iso(trained_at)),
            (RECENT15_VERSION, "baseline_recent15", to_iso(trained_at)),
            (DOW_MEAN_VERSION, "baseline_dow_mean", to_iso(trained_at)),
        ],
    )
    conn.commit()


def insert_prediction(
    conn: sqlite3.Connection,
    segment_id: str,
    target_time: datetime,
    horizon: int,
    predicted: float | None,
    actual: float | None,
    *,
    model_version: str = PERSISTENCE_VERSION,
    quality: str = "ok",
) -> None:
    """`traffic_prediction`에 합성 예측 1행을 넣는다. base_time은 target_time − horizon."""
    base = target_time - timedelta(minutes=horizon)
    abs_error = None if predicted is None or actual is None else abs(predicted - actual)
    conn.execute(
        "INSERT INTO traffic_prediction"
        " (segment_id, base_time, executed_at, horizon, target_time, target_var, predicted_value,"
        "  model_version, input_quality, actual_value, abs_error)"
        " VALUES (?, ?, ?, ?, ?, 'speed', ?, ?, ?, ?, ?)",
        (
            segment_id,
            to_iso(base),
            to_iso(base),
            horizon,
            to_iso(target_time),
            predicted,
            model_version,
            quality,
            actual,
            abs_error,
        ),
    )
    conn.commit()
