"""모델 평가 (C-04 v1, SPEC 8장). `prediction.evaluate` 진입점의 본체.

기간 `[now − days, now)`의 예측 중 `actual_value`·`predicted_value`가 모두 있고,
target_time이 평일·비공휴일(`calendar_info.is_holiday`)이며 `eval_window`(양끝 포함) 안인
것만 평가한다. `calendar_info`에 해당 날짜 행이 없으면 주말만 제외하고 경고를 남긴다.

테이블에 horizon 컬럼이 없으므로 horizon은 `regime` 값에 `h{분}:` 접두어로 표현한다
(예: `h15:all`, `h30:congestion_onset`). regime은 실제값 기준이다.
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from datetime import datetime, time, timedelta

from common.grades import grade
from common.logsetup import get_logger
from common.timeutil import parse_iso, to_iso
from config.settings import Settings
from prediction.baseline import TARGET_VAR

log = get_logger(__name__)

EVAL_TYPE = "live"
REGIMES: tuple[str, ...] = ("all", "free_flow", "congested", "congestion_onset")
ONSET_LOOKBACK = timedelta(minutes=15)  # congestion_onset 판정에 비교할 직전 bin 간격 (SPEC 8.1)

# (model_version, horizon, segment_id 또는 None=전체, regime) → [(predicted, actual)]
Samples = dict[tuple[str, int, str | None, str], list[tuple[float, float]]]


def run(conn: sqlite3.Connection, now: datetime, days: int, settings: Settings) -> int:
    """C-04 평가 행을 `model_evaluation`에 저장하고 저장한 행 수를 돌려준다.

    같은 (model_version, eval_type, period_end 날짜, segment_id, regime) 행이 있으면 교체한다.
    표본이 0인 조합은 행을 만들지 않는다. 예외 시 rollback 후 다시 던진다.
    """
    period_start = now - timedelta(days=days)
    samples = _collect(conn, now, period_start, settings)
    if not samples:
        return 0
    today = to_iso(now)[:10]
    count = 0
    try:
        for (model_version, horizon, segment, regime_name), pairs in sorted(
            samples.items(), key=lambda item: (item[0][0], item[0][1], item[0][2] or "", item[0][3])
        ):
            n, mae, rmse, wape, accuracy = _metrics(pairs, settings)
            regime = f"h{horizon}:{regime_name}"
            conn.execute(
                "DELETE FROM model_evaluation WHERE model_version = ? AND eval_type = ?"
                " AND substr(period_end, 1, 10) = ? AND segment_id IS ? AND regime = ?",
                (model_version, EVAL_TYPE, today, segment, regime),
            )
            conn.execute(
                "INSERT INTO model_evaluation"
                " (model_version, eval_type, period_start, period_end, segment_id, regime,"
                "  n_samples, mae, rmse, wape, grade_accuracy, evaluated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    model_version,
                    EVAL_TYPE,
                    to_iso(period_start),
                    to_iso(now),
                    segment,
                    regime,
                    n,
                    mae,
                    rmse,
                    wape,
                    accuracy,
                    to_iso(now),
                ),
            )
            count += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    log.info("평가 %d행 저장 (기간 %s ~ %s)", count, to_iso(period_start), to_iso(now))
    return count


def _load_calendar(conn: sqlite3.Connection) -> dict[str, int]:
    """date → is_holiday."""
    return {
        r["date"]: r["is_holiday"]
        for r in conn.execute("SELECT date, is_holiday FROM calendar_info")
    }


def _onset_reference(
    conn: sqlite3.Connection,
    segment_id: str,
    target: datetime,
    now: datetime,
    cache: dict[tuple[str, str], float | None],
) -> float | None:
    """congestion_onset 판정 기준: 같은 구간 `target − 15분` bin의 실제 speed. 없으면 None.

    보정값(imputed)·결측(missing)은 실제 비교 근거로 쓰지 않는다 (Review Focus 1).
    """
    key = (segment_id, to_iso(target))
    if key not in cache:
        row = conn.execute(
            "SELECT speed FROM segment_traffic_5min"
            " WHERE segment_id = ? AND bin_time = ? AND speed IS NOT NULL"
            " AND is_imputed = 0 AND quality_flag NOT IN ('imputed', 'missing')"
            " AND available_at <= ?",
            (segment_id, to_iso(target - ONSET_LOOKBACK), to_iso(now)),
        ).fetchone()
        cache[key] = float(row["speed"]) if row is not None else None
    return cache[key]


def _collect(
    conn: sqlite3.Connection, now: datetime, period_start: datetime, settings: Settings
) -> Samples:
    """평가 대상 표본을 regime별로 모은다."""
    rows = conn.execute(
        "SELECT model_version, segment_id, horizon, target_time, predicted_value, actual_value"
        " FROM traffic_prediction"
        " WHERE target_var = ? AND actual_value IS NOT NULL AND predicted_value IS NOT NULL"
        " AND target_time >= ? AND target_time < ?",
        (TARGET_VAR, to_iso(period_start), to_iso(now)),
    ).fetchall()
    if not rows:
        return {}
    calendar = _load_calendar(conn)
    window_start = time.fromisoformat(settings.eval_window[0])
    window_end = time.fromisoformat(settings.eval_window[1])
    onset_cache: dict[tuple[str, str], float | None] = {}
    warned_missing_calendar: set[str] = set()  # 같은 날짜 경고는 1회만

    samples: Samples = defaultdict(list)
    for r in rows:
        target = parse_iso(r["target_time"])
        if not (window_start <= target.time() <= window_end):
            continue
        if target.weekday() >= 5:  # 토·일은 달력과 무관하게 제외한다
            continue
        date_key = to_iso(target)[:10]
        if date_key in calendar:
            if calendar[date_key] == 1:
                continue
        elif date_key not in warned_missing_calendar:
            # 평일인데 달력 행이 없으면 공휴일 여부를 모른다. 주말만 제외하고 평가한다 (C-04).
            warned_missing_calendar.add(date_key)
            log.warning(
                "calendar_info에 %s 행이 없어 공휴일을 확인할 수 없다. 주말만 제외하고 평가한다.",
                date_key,
            )
        actual = float(r["actual_value"])
        predicted = float(r["predicted_value"])
        model_version, horizon, segment = r["model_version"], r["horizon"], r["segment_id"]

        actual_grade = grade(actual, settings)
        ref = _onset_reference(conn, segment, target, now, onset_cache)
        onset = ref is not None and actual <= ref * (1 - settings.congestion_onset_drop)
        for scope in (None, segment):  # None = 전체
            samples[(model_version, horizon, scope, "all")].append((predicted, actual))
            if actual_grade == "free":
                samples[(model_version, horizon, scope, "free_flow")].append((predicted, actual))
            elif actual_grade == "jam":
                samples[(model_version, horizon, scope, "congested")].append((predicted, actual))
            if onset:
                samples[(model_version, horizon, scope, "congestion_onset")].append(
                    (predicted, actual)
                )
    return samples


def _metrics(
    pairs: list[tuple[float, float]], settings: Settings
) -> tuple[int, float, float, float | None, float]:
    """(n_samples, mae, rmse, wape, grade_accuracy). wape 분모가 0이면 None (C-04)."""
    errors = [p - a for p, a in pairs]
    n = len(pairs)
    mae = sum(abs(e) for e in errors) / n
    rmse = math.sqrt(sum(e * e for e in errors) / n)
    denom = sum(abs(a) for _, a in pairs)
    wape = sum(abs(e) for e in errors) / denom if denom > 0 else None
    hits = sum(1 for p, a in pairs if grade(p, settings) == grade(a, settings))
    return n, mae, rmse, wape, hits / n
