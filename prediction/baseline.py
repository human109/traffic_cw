"""현재 속도 유지(persistence) 기준 모델 (SPEC 7장, 계약 C-01·C-04·C-06).

가장 최근에 쓸 수 있는 5분 bin의 속도를 모든 horizon의 예측값으로 쓴다.
"쓸 수 있는" bin은 `available_at ≤ now`인 bin이다(미래 정보 사용 금지, AGENTS.md 6장 3).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from common.logsetup import get_logger
from common.timeutil import floor_5min, parse_iso, to_iso
from config.settings import Settings

log = get_logger(__name__)

PERSISTENCE_VERSION = "baseline_persistence"
TARGET_VAR = "speed"
BIN = timedelta(minutes=5)

# segment_traffic_5min.quality_flag → traffic_prediction.input_quality (C-01)
_FLAG_TO_QUALITY = {"ok": "ok", "partial": "degraded", "unweighted": "degraded"}


def ensure_registry(conn: sqlite3.Connection, now: datetime) -> None:
    """`model_registry`에 persistence 모델 행이 없으면 넣는다. horizon별 모델은 Slice 2부터 쓴다."""
    conn.execute(
        "INSERT OR IGNORE INTO model_registry"
        " (model_version, model_type, target_var, horizon, trained_at, is_active)"
        " VALUES (?, ?, ?, 0, ?, 1)",
        (PERSISTENCE_VERSION, "baseline_persistence", TARGET_VAR, to_iso(now)),
    )


def _is_stale(bin_time: datetime, now: datetime, stale_minutes: int) -> bool:
    return now - (bin_time + BIN) > timedelta(minutes=stale_minutes)


def latest_usable_bin(
    conn: sqlite3.Connection, segment_id: str, now: datetime, stale_minutes: int
) -> sqlite3.Row | None:
    """`available_at ≤ now`이고 오래되지 않은 최신 bin을 돌려준다. 없으면 None.

    오래되지 않은 bin 후보(최대 몇 개)를 시각으로 직접 계산해 기본키로 조회한다.
    문자열 정렬·비교에 의존하지 않고, 비교는 datetime으로 한다.
    """
    candidate = floor_5min(now)
    while not _is_stale(candidate, now, stale_minutes):
        row = conn.execute(
            "SELECT bin_time, available_at, speed, quality_flag FROM segment_traffic_5min"
            " WHERE segment_id = ? AND bin_time = ?",
            (segment_id, to_iso(candidate)),
        ).fetchone()
        if row is not None and parse_iso(row["available_at"]) <= now:
            return row
        candidate -= BIN
    return None


def predict_segment(
    conn: sqlite3.Connection, segment_id: str, now: datetime, settings: Settings
) -> int:
    """한 구간의 horizon별 예측을 저장하고 새로 저장한 행 수를 돌려준다."""
    row = latest_usable_bin(conn, segment_id, now, settings.stale_minutes)
    if row is None:
        base_time = floor_5min(now) - BIN
        value: float | None = None
        quality = "skipped"
    else:
        base_time = parse_iso(row["bin_time"])
        if row["speed"] is None:
            value, quality = None, "skipped"
        else:
            value = float(row["speed"])
            # 계약에 없는 플래그(예: Slice 1의 imputed)는 보수적으로 degraded로 본다.
            quality = _FLAG_TO_QUALITY.get(row["quality_flag"], "degraded")

    inserted = 0
    for h in settings.horizons:
        cur = conn.execute(
            "INSERT OR IGNORE INTO traffic_prediction"
            " (segment_id, base_time, executed_at, horizon, target_time, target_var,"
            "  predicted_value, model_version, input_quality)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                segment_id,
                to_iso(base_time),
                to_iso(now),
                h,
                to_iso(base_time + timedelta(minutes=h)),
                TARGET_VAR,
                value,
                PERSISTENCE_VERSION,
                quality,
            ),
        )
        inserted += cur.rowcount
    if quality == "skipped":
        log.info("예측 건너뜀: segment=%s base_time=%s", segment_id, to_iso(base_time))
    return inserted


def predict_all(conn: sqlite3.Connection, now: datetime, settings: Settings) -> int:
    """`is_target=1`인 모든 구간을 예측하고 commit한다. 새로 저장한 행 수를 돌려준다."""
    ensure_registry(conn, now)
    segments = [
        r[0]
        for r in conn.execute(
            "SELECT segment_id FROM road_segment WHERE is_target = 1 ORDER BY seq, segment_id"
        )
    ]
    total = sum(predict_segment(conn, sid, now, settings) for sid in segments)
    conn.commit()
    return total


def backfill(conn: sqlite3.Connection, now: datetime) -> int:
    """대상 시각이 지난 예측에 실제값·절대오차를 채우고 commit한다. 갱신 건수를 돌려준다.

    실제값은 같은 구간·`bin_time == target_time`이고 `available_at ≤ now`, speed NOT NULL인 집계다.
    예측값이 NULL(skipped)이면 실제값만 넣고 오차는 NULL로 둔다.
    """
    pending = conn.execute(
        "SELECT id, segment_id, target_time, predicted_value FROM traffic_prediction"
        " WHERE actual_value IS NULL AND target_var = ?",
        (TARGET_VAR,),
    ).fetchall()
    updated = 0
    for p in pending:
        if parse_iso(p["target_time"]) > now:
            continue
        actual_row = conn.execute(
            "SELECT available_at, speed FROM segment_traffic_5min"
            " WHERE segment_id = ? AND bin_time = ?",
            (p["segment_id"], p["target_time"]),
        ).fetchone()
        if actual_row is None or actual_row["speed"] is None:
            continue
        if parse_iso(actual_row["available_at"]) > now:
            continue
        actual = float(actual_row["speed"])
        pred = p["predicted_value"]
        abs_error = None if pred is None else abs(float(pred) - actual)
        conn.execute(
            "UPDATE traffic_prediction SET actual_value = ?, abs_error = ? WHERE id = ?",
            (actual, abs_error, p["id"]),
        )
        updated += 1
    conn.commit()
    return updated
