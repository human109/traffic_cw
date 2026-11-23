"""현재 속도 유지(persistence) 기준 모델과 예측 저장·실제값 갱신 공용 코드 (SPEC 7장, C-04 v1).

persistence는 가장 최근에 쓸 수 있는 5분 bin의 속도를 모든 horizon의 예측값으로 쓴다.
"쓸 수 있는" bin은 `available_at ≤ now`인 bin이다(미래 정보 사용 금지, AGENTS.md 6장 3).

이 모듈은 기준 모델 3종의 모델 버전 상수, `model_registry` 등록, 예측 행 저장
(skipped 덮어쓰기 규칙), 실제값 갱신(backfill) 규칙을 함께 담는다.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from common.logsetup import get_logger
from common.timeutil import floor_5min, parse_iso, require_aware, to_iso
from config.settings import Settings

log = get_logger(__name__)

PERSISTENCE_VERSION = "baseline_persistence"
RECENT15_VERSION = "baseline_recent15"
DOW_MEAN_VERSION = "baseline_dow_mean"
TARGET_VAR = "speed"
BIN = timedelta(minutes=5)

# (model_version, model_type) — C-04의 기준 모델 3종. model_registry.horizon=0(horizon 공통).
BASELINE_MODELS: tuple[tuple[str, str], ...] = (
    (PERSISTENCE_VERSION, "baseline_persistence"),
    (RECENT15_VERSION, "baseline_recent15"),
    (DOW_MEAN_VERSION, "baseline_dow_mean"),
)

# segment_traffic_5min.quality_flag → traffic_prediction.input_quality (C-01)
# imputed(보정값)는 실제 관측이 아니므로 degraded다. 계약에 없는 새 플래그도 보수적으로 degraded.
FLAG_TO_QUALITY: dict[str, str] = {
    "ok": "ok",
    "partial": "degraded",
    "unweighted": "degraded",
    "imputed": "degraded",
}

# 실제값으로 쓸 수 없는 bin 플래그 (C-04 backfill 규칙: 보정값·결측을 실제값처럼 쓰지 않는다)
_NOT_ACTUAL_FLAGS = ("imputed", "missing")


def ensure_registry(conn: sqlite3.Connection, now: datetime) -> None:
    """기준 모델 3종을 `model_registry`에 등록한다. 이미 있으면 그대로 둔다."""
    conn.executemany(
        "INSERT OR IGNORE INTO model_registry"
        " (model_version, model_type, target_var, horizon, trained_at, is_active)"
        " VALUES (?, ?, ?, 0, ?, 1)",
        [(version, model_type, TARGET_VAR, to_iso(now)) for version, model_type in BASELINE_MODELS],
    )


def _is_stale(bin_time: datetime, now: datetime, stale_minutes: int) -> bool:
    return now - (bin_time + BIN) > timedelta(minutes=stale_minutes)


def road_order_key(road_name: str, settings: Settings) -> tuple[int, str]:
    """도로 정렬 키 (C-01 v1.4).

    `settings.corridors` 안의 도로는 그 인덱스 순서, 목록에 없는 도로는 목록 뒤에서
    `road_name` 순서다.
    """
    try:
        return (settings.corridors.index(road_name), "")
    except ValueError:
        return (len(settings.corridors), road_name)


def ordered_target_segments(conn: sqlite3.Connection, settings: Settings) -> list[str]:
    """예측 대상(`is_target=1`) 구간을 (도로 순서, seq)로 정렬해 돌려준다 (C-01 v1.4).

    `ORDER BY seq`만 쓰면 여러 도로의 구간이 섞이므로, 도로 순서를 먼저 적용한다.
    """
    rows = conn.execute(
        "SELECT segment_id, road_name, seq FROM road_segment WHERE is_target = 1"
    ).fetchall()
    ordered = sorted(
        rows,
        key=lambda r: (*road_order_key(r["road_name"], settings), r["seq"], r["segment_id"]),
    )
    return [r["segment_id"] for r in ordered]


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


def _base_time(
    conn: sqlite3.Connection, segment_id: str, now: datetime, settings: Settings
) -> tuple[datetime, sqlite3.Row | None]:
    """기준 모델 3종이 함께 쓰는 base_time과 그 근거 bin. bin이 없으면 `floor_5min(now) − 5분`."""
    latest = latest_usable_bin(conn, segment_id, now, settings.stale_minutes)
    base = parse_iso(latest["bin_time"]) if latest is not None else floor_5min(now) - BIN
    return base, latest


def record_prediction(
    conn: sqlite3.Connection,
    segment_id: str,
    base_time: datetime,
    now: datetime,
    horizon: int,
    value: float | None,
    quality: str,
    model_version: str,
) -> int:
    """예측 1행을 저장하고 저장(신규·덮어쓰기)했으면 1을 돌려준다 (C-04).

    같은 키(segment, base_time, horizon, target_var, model_version) 행이 `skipped`이고
    새 예측이 있으면 덮어쓴다. `ok`·`degraded` 행은 덮어쓰지 않는다.
    덮어쓸 때 이미 채워진 `actual_value`가 있으면 `abs_error`도 함께 갱신한다.
    """
    target_time = base_time + timedelta(minutes=horizon)
    existing = conn.execute(
        "SELECT id, input_quality, actual_value FROM traffic_prediction"
        " WHERE segment_id = ? AND base_time = ? AND horizon = ? AND target_var = ?"
        " AND model_version = ?",
        (segment_id, to_iso(base_time), horizon, TARGET_VAR, model_version),
    ).fetchone()
    executed_at = to_iso(now)
    if existing is None:
        conn.execute(
            "INSERT INTO traffic_prediction"
            " (segment_id, base_time, executed_at, horizon, target_time, target_var,"
            "  predicted_value, model_version, input_quality)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                segment_id,
                to_iso(base_time),
                executed_at,
                horizon,
                to_iso(target_time),
                TARGET_VAR,
                value,
                model_version,
                quality,
            ),
        )
        return 1
    if existing["input_quality"] == "skipped" and quality != "skipped":
        actual = existing["actual_value"]
        abs_error = None if value is None or actual is None else abs(value - actual)
        conn.execute(
            "UPDATE traffic_prediction SET predicted_value = ?, input_quality = ?,"
            " executed_at = ?, abs_error = ? WHERE id = ?",
            (value, quality, executed_at, abs_error, existing["id"]),
        )
        return 1
    return 0


def predict_persistence(
    conn: sqlite3.Connection,
    segment_id: str,
    now: datetime,
    base_time: datetime,
    latest: sqlite3.Row | None,
    settings: Settings,
) -> int:
    """한 구간의 persistence 예측을 저장하고 저장한 행 수를 돌려준다."""
    if latest is None or latest["speed"] is None:
        value: float | None = None
        quality = "skipped"
    else:
        value = float(latest["speed"])
        quality = FLAG_TO_QUALITY.get(latest["quality_flag"], "degraded")

    total = 0
    for h in settings.horizons:
        total += record_prediction(
            conn, segment_id, base_time, now, h, value, quality, PERSISTENCE_VERSION
        )
    if quality == "skipped":
        log.info("persistence 예측 건너뜀: segment=%s base_time=%s", segment_id, to_iso(base_time))
    return total


def predict_all(conn: sqlite3.Connection, now: datetime, settings: Settings) -> int:
    """대상 구간 전체에 기준 모델 3종을 저장하고 commit한다. 저장한 행 수를 돌려준다.

    세 모델은 같은 base_time으로 함께 저장한다(C-04). 예외 시 rollback 후 다시 던진다.
    """
    from prediction import baselines  # 지연 import: baselines가 이 모듈의 상수·함수를 쓴다

    require_aware(now)
    ensure_registry(conn, now)
    segments = ordered_target_segments(conn, settings)
    total = 0
    try:
        for sid in segments:
            base_time, latest = _base_time(conn, sid, now, settings)
            total += predict_persistence(conn, sid, now, base_time, latest, settings)
            total += baselines.predict_recent15(conn, sid, now, base_time, settings)
            total += baselines.predict_dow_mean(conn, sid, now, base_time, settings)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return total


def backfill(conn: sqlite3.Connection, now: datetime, settings: Settings) -> int:
    """대상 시각이 지난 예측에 실제값·절대오차를 채우고 commit한다. 갱신 건수를 돌려준다. (C-04)

    - 실제값은 같은 구간·`bin_time == target_time`이고 `available_at ≤ now`, speed NOT NULL,
      flag가 `imputed`·`missing`이 아닌 bin에서만 채운다.
    - 대상은 `now − backfill_lookback_hours ≤ target_time ≤ now`뿐이다.
    - 예측값이 NULL(skipped)이면 실제값만 넣고 오차는 NULL로 둔다.
    - 예외 시 rollback 후 다시 던진다.
    """
    require_aware(now)
    cutoff = now - timedelta(hours=settings.backfill_lookback_hours)
    pending = conn.execute(
        "SELECT p.id, p.segment_id, p.target_time, p.predicted_value, rs.road_name, rs.seq"
        " FROM traffic_prediction p JOIN road_segment rs ON rs.segment_id = p.segment_id"
        " WHERE p.actual_value IS NULL AND p.target_var = ?"
        " AND p.target_time >= ? AND p.target_time <= ?",
        (TARGET_VAR, to_iso(cutoff), to_iso(now)),
    ).fetchall()
    # 갱신 순서도 예측과 같은 (도로 순서, seq)를 유지한다 (C-01 v1.4).
    pending = sorted(
        pending,
        key=lambda p: (
            *road_order_key(p["road_name"], settings),
            p["seq"],
            parse_iso(p["target_time"]),
            p["id"],
        ),
    )
    updated = 0
    try:
        for p in pending:
            row = conn.execute(
                "SELECT available_at, speed, quality_flag, is_imputed FROM segment_traffic_5min"
                " WHERE segment_id = ? AND bin_time = ?",
                (p["segment_id"], p["target_time"]),
            ).fetchone()
            if row is None or row["speed"] is None:
                continue
            if row["quality_flag"] in _NOT_ACTUAL_FLAGS or row["is_imputed"]:
                continue
            if parse_iso(row["available_at"]) > now:
                continue
            actual = float(row["speed"])
            pred = p["predicted_value"]
            abs_error = None if pred is None else abs(float(pred) - actual)
            conn.execute(
                "UPDATE traffic_prediction SET actual_value = ?, abs_error = ? WHERE id = ?",
                (actual, abs_error, p["id"]),
            )
            updated += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return updated
