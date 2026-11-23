"""`prediction.evaluate` 테스트 (C-04 v1.4, C-06 v2).

synthetic: 예측·실제 값은 테스트가 직접 넣는 합성 값이다. 여기서 나온 지표를
실제 성능으로 보고하지 않는다 (C-04 불변 조건).
"""

from __future__ import annotations

import logging
import math
import sqlite3
from datetime import datetime, timedelta

import pytest

from common.timeutil import to_iso
from prediction import evaluate
from prediction.baseline import PERSISTENCE_VERSION, ensure_registry
from tests.fixtures.synthetic_db import ROAD_A, ROAD_B
from tests.prediction.helpers import insert_bin, insert_prediction, t

NOW = t(23, 10, 0)  # 2026-11-23 월요일 10:00 → 평가 기간 [11-16 10:00, 11-23 10:00)
WINDOW_DAYS = 7  # 기간 안의 평일: 17(화)·18(수)·19(목)·20(금), 주말 21·22


def _eval_rows(
    conn: sqlite3.Connection,
) -> dict[tuple[str, str, str | None, str | None], sqlite3.Row]:
    """키 = (model_version, regime, segment_id, road_name). C-04 v1.4 행 단위."""
    rows = conn.execute("SELECT * FROM model_evaluation").fetchall()
    return {
        (r["model_version"], r["regime"], r["segment_id"], r["road_name"]): r for r in rows
    }


def test_eval_metrics(fixture_conn: sqlite3.Connection) -> None:
    ensure_registry(fixture_conn, NOW)
    # h15 두 표본: 오차 5·10, 실제 40·60(둘 다 원활)
    insert_prediction(fixture_conn, "S1", t(17, 7, 0), 15, 45.0, 40.0)
    insert_prediction(fixture_conn, "S1", t(17, 8, 0), 15, 50.0, 60.0)

    n = evaluate(NOW, conn=fixture_conn, days=WINDOW_DAYS)
    assert n == 4  # (도로 집계·S1) x (all·free_flow)

    rows = _eval_rows(fixture_conn)
    agg = rows[(PERSISTENCE_VERSION, "h15:all", None, ROAD_A)]
    assert agg["eval_type"] == "live"
    assert agg["period_start"] == to_iso(NOW - timedelta(days=WINDOW_DAYS))
    assert agg["period_end"] == to_iso(NOW)
    assert agg["evaluated_at"] == to_iso(NOW)
    assert agg["n_samples"] == 2
    assert agg["mae"] == pytest.approx(7.5)
    assert agg["rmse"] == pytest.approx(math.sqrt(62.5))
    assert agg["wape"] == pytest.approx(15.0 / 100.0)
    assert agg["grade_accuracy"] == pytest.approx(1.0)

    per_seg = rows[(PERSISTENCE_VERSION, "h15:all", "S1", ROAD_A)]
    assert per_seg["n_samples"] == 2
    assert per_seg["mae"] == pytest.approx(7.5)
    assert rows[(PERSISTENCE_VERSION, "h15:free_flow", None, ROAD_A)]["n_samples"] == 2

    # 표본이 0인 조합은 행을 만들지 않는다
    assert (PERSISTENCE_VERSION, "h15:congested", None, ROAD_A) not in rows
    assert (PERSISTENCE_VERSION, "h15:congestion_onset", None, ROAD_A) not in rows
    assert (PERSISTENCE_VERSION, "h5:all", None, ROAD_A) not in rows

    # 같은 날짜·키 재실행 시 교체(행 수 불변)
    assert evaluate(NOW, conn=fixture_conn, days=WINDOW_DAYS) == 4
    assert fixture_conn.execute("SELECT COUNT(*) FROM model_evaluation").fetchone()[0] == 4


def test_eval_aggregates_per_road(fixture_conn_two: sqlite3.Connection) -> None:
    # 두 도로가 모두 예측 대상인 픽스처: 집계 행은 도로마다 따로다 (C-04 v1.4).
    ensure_registry(fixture_conn_two, NOW)
    insert_prediction(fixture_conn_two, "S1", t(17, 7, 0), 15, 45.0, 40.0)
    insert_prediction(fixture_conn_two, "S1", t(17, 8, 0), 15, 50.0, 60.0)
    insert_prediction(fixture_conn_two, "W1", t(17, 7, 0), 15, 42.0, 45.0)
    insert_prediction(fixture_conn_two, "W1", t(17, 8, 0), 15, 48.0, 55.0)

    n = evaluate(NOW, conn=fixture_conn_two, days=WINDOW_DAYS)
    assert n == 8  # (도로 집계 + 구간) x (all·free_flow) x 2도로

    rows = _eval_rows(fixture_conn_two)
    aggregations = {
        (road, regime): row
        for (_m, regime, segment, road), row in rows.items()
        if segment is None
    }
    # h15의 두 regime 모두 ROAD_A·ROAD_B 집계 행이 하나씩이다
    assert set(aggregations) == {
        (ROAD_A, "h15:all"),
        (ROAD_A, "h15:free_flow"),
        (ROAD_B, "h15:all"),
        (ROAD_B, "h15:free_flow"),
    }
    # 두 도로를 합친 행은 없다 — 각 도로 집계는 자기 표본 2개뿐(합치면 4)
    assert aggregations[(ROAD_A, "h15:all")]["n_samples"] == 2
    assert aggregations[(ROAD_B, "h15:all")]["n_samples"] == 2
    assert aggregations[(ROAD_B, "h15:all")]["mae"] == pytest.approx(5.0)  # (3+7)/2
    # 구간 행도 road_name을 채운다(그 구간의 도로)
    assert rows[(PERSISTENCE_VERSION, "h15:all", "S1", ROAD_A)]["road_name"] == ROAD_A
    assert rows[(PERSISTENCE_VERSION, "h15:all", "W1", ROAD_B)]["road_name"] == ROAD_B

    # 같은 날 두 번 실행해도 행 수가 같다(교체 키에 road_name 포함)
    assert evaluate(NOW, conn=fixture_conn_two, days=WINDOW_DAYS) == 8
    assert fixture_conn_two.execute("SELECT COUNT(*) FROM model_evaluation").fetchone()[0] == 8


def test_eval_road_aggregation_unchanged_by_second_road(
    fixture_conn: sqlite3.Connection, fixture_conn_two: sqlite3.Connection
) -> None:
    # 원이대로가 추가되어도 창원대로(ROAD_A) 집계 수치는 바뀌지 않아야 한다 (Review Focus 4).
    for conn in (fixture_conn, fixture_conn_two):
        ensure_registry(conn, NOW)
        insert_prediction(conn, "S1", t(17, 7, 0), 15, 45.0, 40.0)
        insert_prediction(conn, "S1", t(17, 8, 0), 15, 50.0, 60.0)
    # 두 번째 도로 표본은 fixture_conn_two에만 있다
    insert_prediction(fixture_conn_two, "W1", t(17, 7, 0), 15, 30.0, 45.0)
    insert_prediction(fixture_conn_two, "W1", t(17, 8, 0), 15, 35.0, 55.0)

    assert evaluate(NOW, conn=fixture_conn, days=WINDOW_DAYS) == 4
    assert evaluate(NOW, conn=fixture_conn_two, days=WINDOW_DAYS) == 8

    single = _eval_rows(fixture_conn)[(PERSISTENCE_VERSION, "h15:all", None, ROAD_A)]
    two = _eval_rows(fixture_conn_two)[(PERSISTENCE_VERSION, "h15:all", None, ROAD_A)]
    assert single["n_samples"] == two["n_samples"] == 2
    assert single["mae"] == pytest.approx(two["mae"]) == pytest.approx(7.5)
    # W 표본이 ROAD_A 집계에 섞이지 않았다
    assert _eval_rows(fixture_conn_two)[(PERSISTENCE_VERSION, "h15:all", None, ROAD_B)][
        "n_samples"
    ] == 2


def test_grade_accuracy(fixture_conn: sqlite3.Connection) -> None:
    ensure_registry(fixture_conn, NOW)
    # (pred, actual): free↔slow 미적중, jam↔slow 미적중, free↔free 적중
    insert_prediction(fixture_conn, "S1", t(17, 7, 0), 10, 39.9, 45.0)
    insert_prediction(fixture_conn, "S1", t(17, 7, 30), 10, 25.0, 15.0)
    insert_prediction(fixture_conn, "S1", t(17, 8, 0), 10, 45.0, 50.0)

    assert evaluate(NOW, conn=fixture_conn, days=WINDOW_DAYS) == 6  # (도로 집계·S1) x 3 regime
    rows = _eval_rows(fixture_conn)
    agg = rows[(PERSISTENCE_VERSION, "h10:all", None, ROAD_A)]
    assert agg["n_samples"] == 3
    assert agg["grade_accuracy"] == pytest.approx(1.0 / 3.0)
    assert rows[(PERSISTENCE_VERSION, "h10:free_flow", None, ROAD_A)]["n_samples"] == 2
    assert rows[(PERSISTENCE_VERSION, "h10:congested", None, ROAD_A)]["n_samples"] == 1
    assert (PERSISTENCE_VERSION, "h10:congestion_onset", None, ROAD_A) not in rows


def test_eval_regimes(fixture_conn: sqlite3.Connection) -> None:
    ensure_registry(fixture_conn, NOW)
    insert_prediction(fixture_conn, "S1", t(17, 7, 0), 15, 50.0, 50.0)   # free_flow
    insert_prediction(fixture_conn, "S1", t(17, 7, 30), 15, 12.0, 15.0)  # congested
    insert_prediction(fixture_conn, "S1", t(17, 8, 0), 15, 25.0, 30.0)   # onset: 30 ≤ 50×0.7
    insert_prediction(fixture_conn, "S1", t(17, 8, 30), 15, 28.0, 30.0)  # onset 아님: 30 > 35×0.7
    insert_bin(fixture_conn, "S1", t(17, 7, 45), 50.0)
    insert_bin(fixture_conn, "S1", t(17, 8, 15), 35.0)

    assert evaluate(NOW, conn=fixture_conn, days=WINDOW_DAYS) == 8
    rows = _eval_rows(fixture_conn)
    assert rows[(PERSISTENCE_VERSION, "h15:all", None, ROAD_A)]["n_samples"] == 4
    assert rows[(PERSISTENCE_VERSION, "h15:free_flow", None, ROAD_A)]["n_samples"] == 1
    assert rows[(PERSISTENCE_VERSION, "h15:congested", None, ROAD_A)]["n_samples"] == 1
    assert rows[(PERSISTENCE_VERSION, "h15:congestion_onset", None, ROAD_A)]["n_samples"] == 1
    for regime in ("h15:all", "h15:free_flow", "h15:congested", "h15:congestion_onset"):
        assert rows[(PERSISTENCE_VERSION, regime, "S1", ROAD_A)]["n_samples"] == rows[
            (PERSISTENCE_VERSION, regime, None, ROAD_A)
        ]["n_samples"]


def test_eval_excludes_weekend_and_holiday(
    fixture_conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    ensure_registry(fixture_conn, NOW)
    fixture_conn.execute(
        "INSERT INTO calendar_info (date, is_holiday, holiday_name) VALUES ('2026-11-18', 1, '합성 공휴일')"
    )
    fixture_conn.commit()
    insert_prediction(fixture_conn, "S1", t(17, 7, 0), 5, 45.0, 40.0)    # 화요일 → 포함
    insert_prediction(fixture_conn, "S1", t(17, 9, 0), 5, 45.0, 40.0)    # eval_window 끝(포함)
    insert_prediction(fixture_conn, "S1", t(21, 7, 0), 5, 45.0, 40.0)    # 토요일 → 제외
    insert_prediction(fixture_conn, "S1", t(22, 7, 0), 5, 45.0, 40.0)    # 일요일 → 제외
    insert_prediction(fixture_conn, "S1", t(18, 7, 0), 5, 45.0, 40.0)    # 공휴일 → 제외
    insert_prediction(fixture_conn, "S1", t(17, 10, 0), 5, 45.0, 40.0)   # eval_window 밖
    insert_prediction(fixture_conn, "S1", t(17, 6, 55), 5, 45.0, 40.0)   # eval_window 밖

    with caplog.at_level(logging.WARNING):
        assert evaluate(NOW, conn=fixture_conn, days=WINDOW_DAYS) == 4

    rows = _eval_rows(fixture_conn)
    assert rows[(PERSISTENCE_VERSION, "h5:all", None, ROAD_A)]["n_samples"] == 2
    # calendar_info에 없는 평일은 주말만 빼고 평가하며 경고를 남긴다
    calendar_warnings = [r for r in caplog.records if "calendar_info" in r.message]
    assert calendar_warnings  # 경고 자체는 남는다
    # 11-17 표본이 2개여도 같은 날짜 경고는 1회뿐이어야 한다
    assert len(calendar_warnings) == 1


def test_eval_requires_actual_and_predicted(fixture_conn: sqlite3.Connection) -> None:
    ensure_registry(fixture_conn, NOW)
    insert_prediction(fixture_conn, "S1", t(17, 7, 0), 5, 45.0, 40.0)
    insert_prediction(fixture_conn, "S1", t(17, 7, 30), 5, None, 40.0, quality="skipped")
    insert_prediction(fixture_conn, "S1", t(17, 8, 0), 5, 45.0, None, quality="ok")

    # 유효 표본 1개 → (도로 집계·S1) x (all·free_flow) = 4행
    assert evaluate(NOW, conn=fixture_conn, days=WINDOW_DAYS) == 4
    rows = _eval_rows(fixture_conn)
    assert rows[(PERSISTENCE_VERSION, "h5:all", None, ROAD_A)]["n_samples"] == 1
    assert rows[(PERSISTENCE_VERSION, "h5:free_flow", None, ROAD_A)]["n_samples"] == 1


def test_eval_empty(fixture_conn: sqlite3.Connection) -> None:
    ensure_registry(fixture_conn, NOW)
    assert evaluate(NOW, conn=fixture_conn, days=WINDOW_DAYS) == 0
    assert fixture_conn.execute("SELECT COUNT(*) FROM model_evaluation").fetchone()[0] == 0


def test_evaluate_naive_rejected(fixture_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        evaluate(datetime(2026, 11, 23, 10, 0), conn=fixture_conn)


def test_evaluate_non_positive_days_rejected(fixture_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        evaluate(NOW, conn=fixture_conn, days=0)
