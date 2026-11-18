"""D-ML-00 현재 속도 유지(persistence) 기준 모델 테스트.

synthetic: `segment_traffic_5min` 행은 테스트 안에서 직접 넣는 합성 값이다. 성능 수치가 아니다.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from common.timeutil import KST, to_iso
from prediction import backfill_actuals, predict_latest
from prediction.baseline import PERSISTENCE_VERSION


def _t(h: int, m: int, s: int = 0) -> datetime:
    return datetime(2026, 11, 16, h, m, s, tzinfo=KST)


def _insert_bin(
    conn: sqlite3.Connection,
    segment_id: str,
    bin_time: datetime,
    available_at: datetime,
    speed: float | None,
    flag: str = "ok",
) -> None:
    conn.execute(
        "INSERT INTO segment_traffic_5min (segment_id, bin_time, available_at, speed,"
        " n_links_expected, n_links_observed, is_imputed, quality_flag, processed_at)"
        " VALUES (?, ?, ?, ?, 2, 2, 0, ?, ?)",
        (segment_id, to_iso(bin_time), to_iso(available_at), speed, flag, to_iso(available_at)),
    )
    conn.commit()


def _rows(conn: sqlite3.Connection, segment_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM traffic_prediction WHERE segment_id = ? ORDER BY horizon", (segment_id,)
    ).fetchall()


def test_four_horizons(fixture_conn: sqlite3.Connection) -> None:
    _insert_bin(fixture_conn, "S1", _t(7, 0), _t(7, 5, 40), 45.0)
    predict_latest(_t(7, 6), conn=fixture_conn)

    rows = _rows(fixture_conn, "S1")
    assert len(rows) == 4
    assert [r["horizon"] for r in rows] == [5, 10, 15, 30]
    assert [r["target_time"] for r in rows] == [
        to_iso(_t(7, 5)),
        to_iso(_t(7, 10)),
        to_iso(_t(7, 15)),
        to_iso(_t(7, 30)),
    ]
    for r in rows:
        assert r["base_time"] == to_iso(_t(7, 0))
        assert r["predicted_value"] == 45.0
        assert r["input_quality"] == "ok"
        assert r["target_var"] == "speed"
        assert r["model_version"] == PERSISTENCE_VERSION
        assert r["executed_at"] == to_iso(_t(7, 6))
        assert r["actual_value"] is None
        assert r["abs_error"] is None


def test_registry_row(fixture_conn: sqlite3.Connection) -> None:
    predict_latest(_t(7, 6), conn=fixture_conn)
    predict_latest(_t(7, 7), conn=fixture_conn)
    rows = fixture_conn.execute("SELECT * FROM model_registry").fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r["model_version"] == PERSISTENCE_VERSION == "baseline_persistence"
    assert r["model_type"] == "baseline_persistence"
    assert r["target_var"] == "speed"
    assert r["horizon"] == 0
    assert r["is_active"] == 1
    assert r["trained_at"] == to_iso(_t(7, 6))


def test_non_target_segment_ignored(fixture_conn: sqlite3.Connection) -> None:
    _insert_bin(fixture_conn, "S0", _t(7, 0), _t(7, 5, 40), 50.0)
    predict_latest(_t(7, 6), conn=fixture_conn)
    assert _rows(fixture_conn, "S0") == []
    segs = {r[0] for r in fixture_conn.execute("SELECT DISTINCT segment_id FROM traffic_prediction")}
    assert segs == {"S1", "S2", "S3"}


def test_stale_input_skipped(fixture_conn: sqlite3.Connection) -> None:
    _insert_bin(fixture_conn, "S1", _t(6, 20), _t(6, 25, 40), 45.0)
    predict_latest(_t(7, 6), conn=fixture_conn)

    rows = _rows(fixture_conn, "S1")
    assert len(rows) == 4
    for r in rows:
        assert r["predicted_value"] is None
        assert r["input_quality"] == "skipped"
        assert r["base_time"] == to_iso(_t(7, 0))  # floor_5min(07:06) - 5분


def test_no_bin_skipped(fixture_conn: sqlite3.Connection) -> None:
    predict_latest(_t(7, 6), conn=fixture_conn)
    rows = _rows(fixture_conn, "S2")
    assert len(rows) == 4
    assert all(r["input_quality"] == "skipped" and r["predicted_value"] is None for r in rows)


def test_null_speed_skipped(fixture_conn: sqlite3.Connection) -> None:
    _insert_bin(fixture_conn, "S1", _t(7, 0), _t(7, 5), None, flag="missing")
    predict_latest(_t(7, 6), conn=fixture_conn)
    rows = _rows(fixture_conn, "S1")
    assert len(rows) == 4
    for r in rows:
        assert r["predicted_value"] is None
        assert r["input_quality"] == "skipped"
        assert r["base_time"] == to_iso(_t(7, 0))


def test_future_bin_not_used(fixture_conn: sqlite3.Connection) -> None:
    _insert_bin(fixture_conn, "S1", _t(7, 0), _t(7, 5, 40), 45.0)
    _insert_bin(fixture_conn, "S1", _t(7, 5), _t(7, 6, 30), 30.0)
    predict_latest(_t(7, 6), conn=fixture_conn)

    rows = _rows(fixture_conn, "S1")
    assert len(rows) == 4
    assert all(r["base_time"] == to_iso(_t(7, 0)) for r in rows)
    assert all(r["predicted_value"] == 45.0 for r in rows)


@pytest.mark.parametrize("flag", ["partial", "unweighted"])
def test_degraded_flag(fixture_conn: sqlite3.Connection, flag: str) -> None:
    _insert_bin(fixture_conn, "S1", _t(7, 0), _t(7, 5, 40), 45.0, flag=flag)
    predict_latest(_t(7, 6), conn=fixture_conn)
    rows = _rows(fixture_conn, "S1")
    assert len(rows) == 4
    assert all(r["input_quality"] == "degraded" and r["predicted_value"] == 45.0 for r in rows)


def test_backfill(fixture_conn: sqlite3.Connection) -> None:
    _insert_bin(fixture_conn, "S1", _t(7, 0), _t(7, 5, 40), 45.0)
    predict_latest(_t(7, 6), conn=fixture_conn)
    _insert_bin(fixture_conn, "S1", _t(7, 10), _t(7, 15, 40), 40.0)

    n = backfill_actuals(_t(7, 16), conn=fixture_conn)
    assert n == 1

    by_h = {r["horizon"]: r for r in _rows(fixture_conn, "S1")}
    assert by_h[10]["actual_value"] == 40.0
    assert by_h[10]["abs_error"] == pytest.approx(5.0)
    assert by_h[30]["actual_value"] is None
    assert by_h[30]["abs_error"] is None
    # 07:05·07:15 bin은 없으므로 그대로 NULL
    assert by_h[5]["actual_value"] is None
    assert by_h[15]["actual_value"] is None


def test_backfill_respects_available_at(fixture_conn: sqlite3.Connection) -> None:
    _insert_bin(fixture_conn, "S1", _t(7, 0), _t(7, 5, 40), 45.0)
    predict_latest(_t(7, 6), conn=fixture_conn)
    _insert_bin(fixture_conn, "S1", _t(7, 10), _t(7, 15, 40), 40.0)

    assert backfill_actuals(_t(7, 15), conn=fixture_conn) == 0
    by_h = {r["horizon"]: r for r in _rows(fixture_conn, "S1")}
    assert by_h[10]["actual_value"] is None


def test_backfill_skipped_prediction_gets_actual_only(fixture_conn: sqlite3.Connection) -> None:
    predict_latest(_t(7, 6), conn=fixture_conn)  # S1 bin 없음 → skipped, base 07:00
    _insert_bin(fixture_conn, "S1", _t(7, 10), _t(7, 15, 40), 40.0)

    backfill_actuals(_t(7, 16), conn=fixture_conn)
    by_h = {r["horizon"]: r for r in _rows(fixture_conn, "S1")}
    assert by_h[10]["predicted_value"] is None
    assert by_h[10]["actual_value"] == 40.0
    assert by_h[10]["abs_error"] is None


def test_backfill_ignores_null_speed(fixture_conn: sqlite3.Connection) -> None:
    _insert_bin(fixture_conn, "S1", _t(7, 0), _t(7, 5, 40), 45.0)
    predict_latest(_t(7, 6), conn=fixture_conn)
    _insert_bin(fixture_conn, "S1", _t(7, 10), _t(7, 15), None, flag="missing")

    assert backfill_actuals(_t(7, 16), conn=fixture_conn) == 0


def test_rerun_no_duplicate(fixture_conn: sqlite3.Connection) -> None:
    _insert_bin(fixture_conn, "S1", _t(7, 0), _t(7, 5, 40), 45.0)
    first = predict_latest(_t(7, 6), conn=fixture_conn)
    count1 = fixture_conn.execute("SELECT COUNT(*) FROM traffic_prediction").fetchone()[0]
    second = predict_latest(_t(7, 6), conn=fixture_conn)
    count2 = fixture_conn.execute("SELECT COUNT(*) FROM traffic_prediction").fetchone()[0]
    assert count1 == count2 == 12  # 대상 구간 3개 x horizon 4개
    assert first == 12
    assert second == 0


def test_naive_rejected(fixture_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        predict_latest(datetime(2026, 11, 16, 7, 6), conn=fixture_conn)
    with pytest.raises(ValueError):
        backfill_actuals(datetime(2026, 11, 16, 7, 16), conn=fixture_conn)
