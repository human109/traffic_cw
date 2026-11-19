"""대시보드 데이터 조회(읽기 전용, 순수 함수). 근거: SPEC 9.1~9.3.

- DB에 쓰지 않는다. `conn`은 호출자가 넘기고 닫지 않는다.
- 값이 없으면 '-'로 표시한다. 임의 수치를 만들지 않는다.
- 시각 문자열은 모두 `YYYY-MM-DDTHH:MM:SS+09:00`(C-01)이므로 문자열 비교가 시각 비교와 같다.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

from common.grades import GRADE_LABEL, grade as _grade
from common.timeutil import parse_iso, require_aware, to_iso
from config.settings import Settings

# dev-ml의 기준 모델 버전 문자열과 같은 값. prediction 내부 코드는 import하지 않는다(AGENTS.md 1장 4).
BASELINE_MODEL_VERSION = "baseline_persistence"

DASH = "-"


def grade(speed: float | None, s: Settings) -> str | None:
    """속도 기준 파생 혼잡 등급(SPEC 9.2). 경계는 config 공용 값을 쓴다."""
    g = _grade(speed, s)
    return GRADE_LABEL.get(g) if g is not None else None


def fmt(value: float | None) -> str:
    """표시용 문자열. None이면 '-', 아니면 정수 반올림(0.5는 올림)."""
    if value is None:
        return DASH
    return str(int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))


def delay_minutes(latest_available_at: datetime | None, now: datetime) -> float | None:
    """최신 데이터가 쓸 수 있게 된 시각부터 `now`까지의 지연(분). 데이터가 없으면 None."""
    require_aware(now)
    if latest_available_at is None:
        return None
    require_aware(latest_available_at)
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
    require_aware(now)
    now_iso = to_iso(now)
    segments = conn.execute(
        "SELECT segment_id, start_node, end_node FROM road_segment WHERE is_target = 1 ORDER BY seq"
    ).fetchall()

    rows: list[dict[str, str]] = []
    for seg in segments:
        sid = seg[0]
        row: dict[str, str] = {"구간": sid, "이름": f"{seg[1]} → {seg[2]}"}
        latest = conn.execute(
            "SELECT bin_time, speed, quality_flag FROM segment_traffic_5min"
            " WHERE segment_id = ? AND available_at <= ? ORDER BY bin_time DESC LIMIT 1",
            (sid, now_iso),
        ).fetchone()
        speed = latest[1] if latest else None
        flag = latest[2] if latest else None
        row["현재 속도"] = fmt(speed)
        row["상태"] = grade(speed, s) or DASH
        # 품질 열 매핑
        if flag is None:
            quality_disp = DASH
        elif flag == "ok":
            quality_disp = "ok"
        elif flag == "imputed":
            quality_disp = "보정"
        elif flag in ("partial", "unweighted"):
            quality_disp = "부분"
        elif flag == "missing":
            quality_disp = DASH
        else:
            quality_disp = DASH
        row["품질"] = quality_disp

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

    columns = ["구간", "이름", "현재 속도", "상태", "품질", *[f"{h}분 후" for h in s.horizons]]
    return pd.DataFrame(rows, columns=columns)


def timeseries(conn: sqlite3.Connection, segment_id: str, start: datetime, end: datetime, horizon: int, model_version: str, now: datetime) -> pd.DataFrame:
    """구간 시계열: 시계열 그래프용 실제·예측.
    `시각`은 target_time 기준 ISO 문자열, `실제`/`예측`은 float, 없으면 NaN.
    예측은 executed_at <= now 인 것만, 실제값 조인은 available_at <= now 이고 quality_flag가 imputed/missing이 아닌 bin만 사용.
    """
    require_aware(start)
    require_aware(end)
    require_aware(now)
    start_iso = to_iso(start)
    end_iso = to_iso(end)
    now_iso = to_iso(now)
    rows = conn.execute(
        """
        SELECT p.target_time, p.predicted_value, s.speed
        FROM traffic_prediction p
        LEFT JOIN segment_traffic_5min s
          ON s.segment_id = p.segment_id AND s.bin_time = p.target_time
         AND s.quality_flag NOT IN ('imputed', 'missing')
         AND s.available_at <= ?
        WHERE p.segment_id = ?
          AND p.horizon = ?
          AND p.model_version = ?
          AND p.target_var = 'speed'
          AND p.executed_at <= ?
          AND p.target_time >= ?
          AND p.target_time < ?
        ORDER BY p.target_time
        """,
        (now_iso, segment_id, horizon, model_version, now_iso, start_iso, end_iso),
    ).fetchall()
    data = []
    for r in rows:
        data.append({
            "시각": r[0],
            "실제": float(r[2]) if r[2] is not None else float("nan"),
            "예측": float(r[1]) if r[1] is not None else float("nan"),
        })
    if not data:
        return pd.DataFrame(columns=["시각", "실제", "예측"])
    return pd.DataFrame(data)


def heatmap(conn: sqlite3.Connection, start: datetime, end: datetime, now: datetime) -> pd.DataFrame:
    """시간×구간 히트맵: index=bin_time, columns=segment_id, value=speed.
    missing은 NaN. 히트맵은 보정값(imputed) 포함하여 보여주며, 사용 가능 시점 기준 available_at <= now 만 반영한다.
    """
    require_aware(start)
    require_aware(end)
    require_aware(now)
    start_iso = to_iso(start)
    end_iso = to_iso(end)
    now_iso = to_iso(now)
    # 대상 구간 순서
    segments = [r[0] for r in conn.execute("SELECT segment_id FROM road_segment WHERE is_target = 1 ORDER BY seq")]
    if not segments:
        return pd.DataFrame()
    rows = conn.execute(
        "SELECT segment_id, bin_time, speed FROM segment_traffic_5min WHERE bin_time >= ? AND bin_time < ? AND available_at <= ? AND speed IS NOT NULL",
        (start_iso, end_iso, now_iso),
    ).fetchall()
    if not rows:
        # 빈 프레임이지만 컬럼은 유지
        return pd.DataFrame(columns=segments)
    df = pd.DataFrame(rows, columns=["segment_id", "bin_time", "speed"])
    piv = df.pivot(index="bin_time", columns="segment_id", values="speed")
    # 컬럼 순서 고정
    piv = piv.reindex(columns=segments)
    # 인덱스 정렬
    piv = piv.sort_index()
    return piv


def evaluation_table(conn: sqlite3.Connection, days: int = 7) -> pd.DataFrame:
    """model_evaluation 최신 행 + 기준 모델 대비 개선율.
    개선율 = 1 - MAE / persistence MAE (persistence 없음 → NaN)
    """
    cols = ["model_version", "eval_type", "period_start", "period_end", "segment_id", "regime", "n_samples", "mae", "rmse", "wape", "grade_accuracy", "evaluated_at"]
    # 최신 평가 시각
    max_row = conn.execute("SELECT MAX(evaluated_at) FROM model_evaluation WHERE eval_type = 'live'").fetchone()
    if not max_row or not max_row[0]:
        cols_out = cols + ["개선율"]
        return pd.DataFrame(columns=cols_out)
    max_eval = parse_iso(max_row[0])
    since_iso = to_iso(max_eval - timedelta(days=days))
    rows = list(conn.execute(
        f"SELECT {', '.join(cols)} FROM model_evaluation WHERE eval_type = 'live' AND evaluated_at >= ? ORDER BY evaluated_at DESC, id DESC",
        (since_iso,),
    ))
    if not rows:
        cols_out = cols + ["개선율"]
        return pd.DataFrame(columns=cols_out)
    df = pd.DataFrame(rows, columns=cols)
    # 개선율 계산
    improvements = []
    for _, row in df.iterrows():
        mae = row.get("mae")
        if mae is None or pd.isna(mae):
            improvements.append(float("nan"))
            continue
        # regime에서 horizon 파싱 (h{분}:...)
        regime = row.get("regime") or ""
        # persistence 행 찾기
        pers = conn.execute(
            """
            SELECT mae FROM model_evaluation
            WHERE eval_type = 'live'
              AND model_version = 'baseline_persistence'
              AND period_start = ?
              AND period_end = ?
              AND segment_id IS ?
              AND regime = ?
            """,
            (row.get("period_start"), row.get("period_end"), row.get("segment_id"), regime),
        ).fetchone()
        pers_mae = pers[0] if pers else None
        if pers_mae is None or pers_mae == 0:
            improvements.append(float("nan"))
        else:
            improvements.append(1.0 - float(mae) / float(pers_mae))
    df["개선율"] = improvements
    return df


def segment_delays(conn: sqlite3.Connection, now: datetime) -> dict[str, float | None]:
    """구간별 최신 데이터 지연(분)."""
    require_aware(now)
    now_iso = to_iso(now)
    segments = [r[0] for r in conn.execute("SELECT segment_id FROM road_segment WHERE is_target = 1 ORDER BY seq")]
    delays: dict[str, float | None] = {}
    for sid in segments:
        r = conn.execute(
            "SELECT MAX(available_at) FROM segment_traffic_5min WHERE segment_id = ? AND available_at <= ? AND speed IS NOT NULL",
            (sid, now_iso),
        ).fetchone()
        latest_str = r[0] if r else None
        latest = parse_iso(latest_str) if latest_str else None
        delays[sid] = delay_minutes(latest, now)
    return delays


def active_models(conn: sqlite3.Connection) -> list[str]:
    """활성 모델 목록을 model_registry에서 조회."""
    rows = conn.execute("SELECT model_version FROM model_registry WHERE is_active = 1 ORDER BY model_version").fetchall()
    return [r[0] for r in rows]


def collection_status(conn: sqlite3.Connection, limit: int = 10) -> pd.DataFrame:
    """최근 `collection_log` 행(최신순)."""
    cols = ["started_at", "finished_at", "source", "status", "http_status",
            "links_expected", "links_received", "record_count", "error_message"]
    cur = conn.execute(
        f"SELECT {', '.join(cols)} FROM collection_log ORDER BY started_at DESC, id DESC LIMIT ?",
        (limit,),
    )
    return pd.DataFrame([tuple(r) for r in cur.fetchall()], columns=cols)
