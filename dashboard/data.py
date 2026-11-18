"""대시보드 데이터 조회(읽기 전용, 순수 함수). 근거: SPEC 9.1~9.3.

- DB에 쓰지 않는다. `conn`은 호출자가 넘기고 닫지 않는다.
- 값이 없으면 '-'로 표시한다. 임의 수치를 만들지 않는다.
- 시각 문자열은 모두 `YYYY-MM-DDTHH:MM:SS+09:00`(C-01)이므로 문자열 비교가 시각 비교와 같다.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

from common.timeutil import parse_iso, to_iso
from config.settings import Settings

# dev-ml의 기준 모델 버전 문자열과 같은 값. prediction 내부 코드는 import하지 않는다(AGENTS.md 1장 4).
BASELINE_MODEL_VERSION = "baseline_persistence"

DASH = "-"


def _require_aware(dt: datetime) -> None:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"timezone 정보가 없는 datetime은 허용하지 않는다: {dt!r}")


def grade(speed: float | None, s: Settings) -> str | None:
    """속도 기준 파생 혼잡 등급(SPEC 9.2). 경계는 config 공용 값을 쓴다."""
    if speed is None:
        return None
    if speed >= s.grade_free_min_kmh:
        return "원활"
    if speed >= s.grade_slow_min_kmh:
        return "서행"
    return "정체"


def fmt(value: float | None) -> str:
    """표시용 문자열. None이면 '-', 아니면 정수 반올림(0.5는 올림)."""
    if value is None:
        return DASH
    return str(int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))


def delay_minutes(latest_available_at: datetime | None, now: datetime) -> float | None:
    """최신 데이터가 쓸 수 있게 된 시각부터 `now`까지의 지연(분). 데이터가 없으면 None."""
    _require_aware(now)
    if latest_available_at is None:
        return None
    _require_aware(latest_available_at)
    return (now - latest_available_at).total_seconds() / 60


def latest_available_at(conn: sqlite3.Connection, now: datetime) -> datetime | None:
    """`available_at ≤ now`이고 속도가 있는 집계 bin 중 가장 최근의 available_at. 없으면 None.

    `missing` bin(speed NULL)의 available_at은 bin 끝 시각(C-01)이라 수집이 멈춰도 계속 늘어나므로 제외한다.
    """
    row = conn.execute(
        "SELECT MAX(available_at) FROM segment_traffic_5min WHERE available_at <= ? AND speed IS NOT NULL",
        (to_iso(now),),
    ).fetchone()
    return parse_iso(row[0]) if row and row[0] is not None else None


def current_table(conn: sqlite3.Connection, now: datetime, s: Settings) -> pd.DataFrame:
    """구간별 현재 속도·상태·예측 표(SPEC 9.3).

    is_target 구간을 seq 순으로 정렬한다. 구간마다 `available_at ≤ now`인 최신 bin과,
    그 bin_time을 base_time으로 하고 `executed_at ≤ now`인 `baseline_persistence` 예측을 쓴다(시점 기준).
    `skipped` 예측과 값이 없는 칸은 '-'. `now`에 tz 정보가 없으면 ValueError.
    """
    now_iso = to_iso(now)
    segments = conn.execute(
        "SELECT segment_id, start_node, end_node FROM road_segment WHERE is_target = 1 ORDER BY seq"
    ).fetchall()

    rows: list[dict[str, str]] = []
    for seg in segments:
        sid = seg[0]
        row: dict[str, str] = {"구간": sid, "이름": f"{seg[1]} → {seg[2]}"}
        latest = conn.execute(
            "SELECT bin_time, speed FROM segment_traffic_5min"
            " WHERE segment_id = ? AND available_at <= ? ORDER BY bin_time DESC LIMIT 1",
            (sid, now_iso),
        ).fetchone()
        speed = latest[1] if latest else None
        row["현재 속도"] = fmt(speed)
        row["상태"] = grade(speed, s) or DASH

        preds: dict[int, float | None] = {}
        if latest:
            for p in conn.execute(
                "SELECT horizon, predicted_value, input_quality FROM traffic_prediction"
                " WHERE segment_id = ? AND base_time = ? AND model_version = ? AND target_var = 'speed'"
                " AND executed_at <= ?",
                (sid, latest[0], BASELINE_MODEL_VERSION, now_iso),
            ):
                preds[p[0]] = None if p[2] == "skipped" else p[1]
        for h in s.horizons:
            row[f"{h}분 후"] = fmt(preds.get(h))
        rows.append(row)

    columns = ["구간", "이름", "현재 속도", "상태", *[f"{h}분 후" for h in s.horizons]]
    return pd.DataFrame(rows, columns=columns)


def collection_status(conn: sqlite3.Connection, limit: int = 10) -> pd.DataFrame:
    """최근 `collection_log` 행(최신순)."""
    cols = ["started_at", "finished_at", "source", "status", "http_status",
            "links_expected", "links_received", "record_count", "error_message"]
    cur = conn.execute(
        f"SELECT {', '.join(cols)} FROM collection_log ORDER BY started_at DESC, id DESC LIMIT ?",
        (limit,),
    )
    return pd.DataFrame([tuple(r) for r in cur.fetchall()], columns=cols)
