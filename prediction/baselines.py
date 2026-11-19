"""기준 모델 recent15·dow_mean (C-04 v1, SPEC 8.2).

- `baseline_recent15`: 최신 사용 가능 bin을 포함한 직전 `recent_mean_minutes`(15분 = 3 bin) 중
  speed가 있는 값의 평균. 그런 값이 2개 미만이면 skipped.
- `baseline_dow_mean`: `available_at ≤ now`인 과거 데이터에서 `target_time`과 같은 요일·같은
  HH:MM bin의 speed 평균(imputed 제외). 서로 다른 주가 `dow_mean_min_weeks`(3) 미만이면 skipped.
  dow_mean의 입력 품질은 근거 bin이 아니라 표본 수로 판단하며, 조건을 충족하면 `ok`다.

두 모델 모두 persistence와 같은 base_time으로 저장되며, 미래 정보는 쓰지 않는다
(AGENTS.md 6장 3).
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from common.logsetup import get_logger
from common.timeutil import parse_iso, to_iso
from config.settings import Settings
from prediction.baseline import (
    BIN,
    DOW_MEAN_VERSION,
    RECENT15_VERSION,
    record_prediction,
)

log = get_logger(__name__)


def _recent_values(
    conn: sqlite3.Connection,
    segment_id: str,
    now: datetime,
    base_time: datetime,
    settings: Settings,
) -> list[tuple[float, str]]:
    """최근 15분 창에서 쓸 수 있는 (speed, quality_flag) 값들.

    창은 base_time을 끝으로 하는 `recent_mean_minutes`분이다. 각 bin의 `available_at`이
    `now`보다 늦으면 아직 쓸 수 없는 미래 정보이므로 제외한다.
    """
    minutes_per_bin = int(BIN.total_seconds() // 60)
    n_bins = max(1, settings.recent_mean_minutes // minutes_per_bin)
    start = base_time - BIN * (n_bins - 1)
    rows = conn.execute(
        "SELECT available_at, speed, quality_flag FROM segment_traffic_5min"
        " WHERE segment_id = ? AND bin_time >= ? AND bin_time <= ?",
        (segment_id, to_iso(start), to_iso(base_time)),
    ).fetchall()
    out: list[tuple[float, str]] = []
    for r in rows:
        if r["speed"] is None:
            continue
        if parse_iso(r["available_at"]) > now:
            continue
        out.append((float(r["speed"]), r["quality_flag"]))
    return out


def predict_recent15(
    conn: sqlite3.Connection, segment_id: str, now: datetime, base_time: datetime, settings: Settings
) -> int:
    """최근 15분 평균 기준 모델로 horizon별 예측을 저장한다. 저장한 행 수를 돌려준다."""
    values = _recent_values(conn, segment_id, now, base_time, settings)
    if len(values) < 2:
        value: float | None = None
        quality = "skipped"
    else:
        value = sum(v for v, _ in values) / len(values)
        # 평균의 근거가 된 bin 중 하나라도 완전 관측이 아니면 degraded다 (C-04).
        quality = "ok" if all(flag == "ok" for _, flag in values) else "degraded"

    total = 0
    for h in settings.horizons:
        total += record_prediction(
            conn, segment_id, base_time, now, h, value, quality, RECENT15_VERSION
        )
    if quality == "skipped":
        log.debug(
            "recent15 예측 건너뜀: segment=%s 사용 가능 값 %d개", segment_id, len(values)
        )
    return total


def _dow_mean_and_weeks(
    conn: sqlite3.Connection,
    segment_id: str,
    now: datetime,
    base_time: datetime,
    target: datetime,
) -> tuple[float | None, int]:
    """(target 같은 요일·같은 HH:MM 과거 값의 평균, 값이 있는 서로 다른 날짜 수).

    "서로 다른 주"는 같은 요일·같은 HH:MM 값이 있는 서로 다른 날짜 수로 센다.
    imputed bin(보정값)은 평균에서 제외한다. `bin_time ≤ base_time`으로 같은 날의
    미래 bin을 쓰지 않게 막는다(미래 정보 금지).
    """
    rows = conn.execute(
        "SELECT bin_time, speed FROM segment_traffic_5min"
        " WHERE segment_id = ? AND speed IS NOT NULL"
        " AND quality_flag != 'imputed' AND is_imputed = 0"
        " AND available_at <= ? AND bin_time <= ? AND substr(bin_time, 12, 5) = ?",
        (segment_id, to_iso(now), to_iso(base_time), target.strftime("%H:%M")),
    ).fetchall()
    dates: set[date] = set()
    values: list[float] = []
    for r in rows:
        bin_time = parse_iso(r["bin_time"])
        if bin_time.weekday() != target.weekday() or bin_time >= target:
            continue
        dates.add(bin_time.date())
        values.append(float(r["speed"]))
    if not values:
        return None, 0
    return sum(values) / len(values), len(dates)


def predict_dow_mean(
    conn: sqlite3.Connection, segment_id: str, now: datetime, base_time: datetime, settings: Settings
) -> int:
    """과거 동일 요일·시간대 평균 기준 모델로 horizon별 예측을 저장한다. 저장한 행 수를 돌려준다."""
    total = 0
    for h in settings.horizons:
        target = base_time + timedelta(minutes=h)
        value, weeks = _dow_mean_and_weeks(conn, segment_id, now, base_time, target)
        if weeks < settings.dow_mean_min_weeks:
            value = None
            quality = "skipped"
        else:
            quality = "ok"  # 표본 수로 판단한다 (C-04)
        total += record_prediction(
            conn, segment_id, base_time, now, h, value, quality, DOW_MEAN_VERSION
        )
        if quality == "skipped":
            log.debug(
                "dow_mean 예측 건너뜀: segment=%s target=%s 표본 %d주", segment_id, to_iso(target), weeks
            )
    return total
