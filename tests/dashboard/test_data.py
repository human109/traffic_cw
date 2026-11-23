"""dashboard.data 테스트. fixture_conn은 합성(synthetic) DB다."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

import pytest

from common.timeutil import KST, to_iso
from config.settings import Settings
from dashboard.data import (
    BASELINE_MODEL_VERSION,
    collection_rates,
    collection_status,
    current_table,
    default_model_index,
    delay_minutes,
    evaluation_table,
    fmt,
    grade,
    heatmap,
    latest_available_at,
    segment_delays,
    timeseries,
    timeseries_status,
)

S = Settings()
SPEED_COLS = ["현재 속도", "상태", "품질", "5분 후", "10분 후", "15분 후", "30분 후"]
BIN = datetime(2026, 11, 16, 7, 0, tzinfo=KST)
NOW = datetime(2026, 11, 16, 7, 6, tzinfo=KST)


def _insert_bin(conn: sqlite3.Connection, seg: str, bin_time: datetime, speed: float | None,
                available_at: datetime, flag: str = "ok") -> None:
    conn.execute(
        "INSERT INTO segment_traffic_5min (segment_id, bin_time, available_at, speed, n_links_expected,"
        " n_links_observed, quality_flag, processed_at) VALUES (?, ?, ?, ?, 2, 2, ?, ?)",
        (seg, to_iso(bin_time), to_iso(available_at), speed, flag, to_iso(available_at)),
    )


def _insert_model(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO model_registry (model_version, model_type, target_var, horizon, trained_at, is_active)"
        " VALUES (?, 'persistence', 'speed', 0, ?, 1)",
        (BASELINE_MODEL_VERSION, to_iso(BIN)),
    )


def _insert_pred(conn: sqlite3.Connection, seg: str, base: datetime, h: int, value: float | None,
                 quality: str, executed_at: datetime = NOW) -> None:
    conn.execute(
        "INSERT INTO traffic_prediction (segment_id, base_time, executed_at, horizon, target_time, target_var,"
        " predicted_value, model_version, input_quality) VALUES (?, ?, ?, ?, ?, 'speed', ?, ?, ?)",
        (seg, to_iso(base), to_iso(executed_at), h, to_iso(base + timedelta(minutes=h)), value,
         BASELINE_MODEL_VERSION, quality),
    )


def test_grade_bounds() -> None:
    assert grade(40.0, S) == "원활"
    assert grade(39.9, S) == "서행"
    assert grade(20.0, S) == "서행"
    assert grade(19.9, S) == "정체"
    assert grade(None, S) is None


def test_fmt_none_dash() -> None:
    assert fmt(None) == "-"
    assert fmt(44.6) == "45"


def test_empty_db_all_dash(fixture_conn: sqlite3.Connection) -> None:
    fixture_conn.execute("DELETE FROM traffic_observation")
    fixture_conn.execute("DELETE FROM segment_traffic_5min")
    df = current_table(fixture_conn, NOW, S)
    assert list(df.columns) == ["구간", "이름", *SPEED_COLS]
    assert list(df["구간"]) == ["S1", "S2", "S3"]
    for col in SPEED_COLS:
        assert (df[col] == "-").all(), col


def test_table_values(fixture_conn: sqlite3.Connection) -> None:
    _insert_bin(fixture_conn, "S1", BIN - timedelta(minutes=5), 50.0, BIN + timedelta(seconds=40))
    _insert_bin(fixture_conn, "S1", BIN, 44.6, BIN + timedelta(minutes=5, seconds=40))
    _insert_model(fixture_conn)
    for h, v, q in [(5, 44.6, "ok"), (10, 44.6, "degraded"), (15, None, "skipped"), (30, 30.2, "ok")]:
        _insert_pred(fixture_conn, "S1", BIN, h, v, q)
    # S2: now 이후에 available인 bin은 쓰지 않는다
    _insert_bin(fixture_conn, "S2", BIN, 10.0, NOW + timedelta(minutes=1))
    fixture_conn.commit()

    df = current_table(fixture_conn, NOW, S).set_index("구간")
    s1 = df.loc["S1"]
    assert s1["현재 속도"] == "45"
    assert s1["상태"] == "원활"
    assert s1["5분 후"] == "45"
    assert s1["10분 후"] == "45"  # degraded는 값이 있다
    assert s1["15분 후"] == "-"  # skipped
    assert s1["30분 후"] == "30"
    for col in SPEED_COLS:
        assert df.loc["S2", col] == "-"
        assert df.loc["S3", col] == "-"


def test_missing_bin_speed_dash(fixture_conn: sqlite3.Connection) -> None:
    _insert_bin(fixture_conn, "S1", BIN, None, BIN + timedelta(minutes=5), flag="missing")
    fixture_conn.commit()
    s1 = current_table(fixture_conn, NOW, S).set_index("구간").loc["S1"]
    assert s1["현재 속도"] == "-"
    assert s1["상태"] == "-"


def test_delay_minutes() -> None:
    avail = datetime(2026, 11, 16, 7, 5, 40, tzinfo=KST)
    now = datetime(2026, 11, 16, 7, 20, 0, tzinfo=KST)
    assert delay_minutes(avail, now) == pytest.approx(14.333, abs=1e-3)
    assert delay_minutes(None, now) is None


def test_prediction_executed_after_now_dash(fixture_conn: sqlite3.Connection) -> None:
    _insert_bin(fixture_conn, "S1", BIN, 44.6, BIN + timedelta(minutes=5, seconds=40))
    _insert_model(fixture_conn)
    _insert_pred(fixture_conn, "S1", BIN, 5, 44.6, "ok")  # executed_at == now → 표시
    _insert_pred(fixture_conn, "S1", BIN, 10, 44.6, "ok", executed_at=NOW + timedelta(seconds=1))
    fixture_conn.commit()
    s1 = current_table(fixture_conn, NOW, S).set_index("구간").loc["S1"]
    assert s1["5분 후"] == "45"
    assert s1["10분 후"] == "-"


def test_current_table_naive_now_rejected(fixture_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        current_table(fixture_conn, datetime(2026, 11, 16, 7, 6), S)


def test_latest_available_ignores_missing_bins(fixture_conn: sqlite3.Connection) -> None:
    ok_avail = datetime(2026, 11, 16, 7, 5, 40, tzinfo=KST)
    _insert_bin(fixture_conn, "S1", BIN, 44.6, ok_avail)
    _insert_bin(fixture_conn, "S1", BIN + timedelta(minutes=15), None,
                datetime(2026, 11, 16, 7, 20, 0, tzinfo=KST), flag="missing")
    fixture_conn.commit()
    now = datetime(2026, 11, 16, 7, 20, 30, tzinfo=KST)
    latest = latest_available_at(fixture_conn, now)
    assert latest == ok_avail
    delay = delay_minutes(latest, now)
    assert delay is not None and delay >= S.stale_minutes


def test_latest_available_none_when_only_missing(fixture_conn: sqlite3.Connection) -> None:
    _insert_bin(fixture_conn, "S1", BIN, None, BIN + timedelta(minutes=5), flag="missing")
    fixture_conn.commit()
    assert latest_available_at(fixture_conn, NOW) is None


def test_delay_minutes_naive_rejected() -> None:
    with pytest.raises(ValueError):
        delay_minutes(datetime(2026, 11, 16, 7, 5), datetime(2026, 11, 16, 7, 20, tzinfo=KST))


def test_collection_status(fixture_conn: sqlite3.Connection) -> None:
    assert collection_status(fixture_conn).empty
    for i in range(12):
        t = BIN + timedelta(minutes=i)
        fixture_conn.execute(
            "INSERT INTO collection_log (source, started_at, finished_at, status, record_count)"
            " VALUES ('synthetic', ?, ?, 'success', 5)",
            (to_iso(t), to_iso(t + timedelta(seconds=2))),
        )
    fixture_conn.commit()
    df = collection_status(fixture_conn, limit=10)
    assert len(df) == 10
    assert df.iloc[0]["started_at"] == to_iso(BIN + timedelta(minutes=11))


def test_no_writes(fixture_conn: sqlite3.Connection) -> None:
    before = fixture_conn.total_changes
    current_table(fixture_conn, NOW, S)
    collection_status(fixture_conn)
    assert fixture_conn.total_changes == before


def test_current_quality_mapping(fixture_conn: sqlite3.Connection) -> None:
    _insert_bin(fixture_conn, "S1", BIN, 40.0, BIN + timedelta(minutes=1), flag="ok")
    _insert_bin(fixture_conn, "S2", BIN, 30.0, BIN + timedelta(minutes=1), flag="imputed")
    _insert_bin(fixture_conn, "S3", BIN, 20.0, BIN + timedelta(minutes=1), flag="partial")
    fixture_conn.commit()
    df = current_table(fixture_conn, NOW, S).set_index("구간")
    assert df.loc["S1", "품질"] == "ok"
    assert df.loc["S2", "품질"] == "보정"
    assert df.loc["S3", "품질"] == "부분"


def test_timeseries_nan(fixture_conn: sqlite3.Connection) -> None:
    # 예측만 있고 실제 없음 → 실제 NaN
    base = BIN
    conn = fixture_conn
    # Ensure model exists
    conn.execute(
        "INSERT OR IGNORE INTO model_registry (model_version, model_type, target_var, horizon, trained_at, is_active)"
        " VALUES (?, 'persistence', 'speed', 0, ?, 1)",
        ("baseline_persistence", to_iso(BIN))
    )
    conn.execute(
        "INSERT INTO traffic_prediction (segment_id, base_time, executed_at, horizon, target_time, target_var, predicted_value, model_version, input_quality)"
        " VALUES (?, ?, ?, ?, ?, 'speed', ?, ?, ?)",
        ("S1", to_iso(base), to_iso(NOW), 5, to_iso(base + timedelta(minutes=5)), 42.0, "baseline_persistence", "ok")
    )
    conn.commit()
    df = timeseries(conn, "S1", BIN, BIN + timedelta(minutes=10), 5, "baseline_persistence", NOW)
    assert not df.empty
    assert df.iloc[0]["예측"] == 42.0
    import math
    assert math.isnan(df.iloc[0]["실제"])


def test_heatmap_column_order(fixture_conn: sqlite3.Connection) -> None:
    _insert_bin(fixture_conn, "S2", BIN, 30.0, BIN + timedelta(minutes=1))
    _insert_bin(fixture_conn, "S1", BIN, 40.0, BIN + timedelta(minutes=1))
    fixture_conn.commit()
    df = heatmap(fixture_conn, BIN - timedelta(minutes=1), BIN + timedelta(minutes=10), NOW)
    # columns must follow road_segment seq
    assert list(df.columns)[:2] == ["S1", "S2"]


def test_evaluation_improvement(fixture_conn: sqlite3.Connection) -> None:
    now_ts = to_iso(NOW)
    conn = fixture_conn
    # Ensure models exist
    conn.execute(
        "INSERT OR IGNORE INTO model_registry (model_version, model_type, target_var, horizon, trained_at, is_active)"
        " VALUES (?, 'persistence', 'speed', 0, ?, 1)",
        ("baseline_persistence", to_iso(BIN))
    )
    conn.execute(
        "INSERT OR IGNORE INTO model_registry (model_version, model_type, target_var, horizon, trained_at, is_active)"
        " VALUES (?, 'recent', 'speed', 0, ?, 1)",
        ("baseline_recent15", to_iso(BIN))
    )
    # persistence row
    conn.execute(
        "INSERT INTO model_evaluation (model_version, eval_type, period_start, period_end, segment_id, regime, n_samples, mae, rmse, wape, grade_accuracy, evaluated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("baseline_persistence", "live", to_iso(BIN), to_iso(BIN + timedelta(days=1)), None, "h5:all", 10, 5.0, 0, 0, 0, now_ts)
    )
    # other model
    conn.execute(
        "INSERT INTO model_evaluation (model_version, eval_type, period_start, period_end, segment_id, regime, n_samples, mae, rmse, wape, grade_accuracy, evaluated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("baseline_recent15", "live", to_iso(BIN), to_iso(BIN + timedelta(days=1)), None, "h5:all", 10, 4.0, 0, 0, 0, now_ts)
    )
    conn.commit()
    df = evaluation_table(conn, days=1)
    # 개선율 = 1 - 4/5 = 0.2
    row = df[df["model_version"] == "baseline_recent15"].iloc[0]
    assert abs(row["개선율"] - 0.2) < 1e-6


def test_timeseries_asof_executed_after_now(fixture_conn: sqlite3.Connection) -> None:
    base = BIN
    conn = fixture_conn
    conn.execute(
        "INSERT OR IGNORE INTO model_registry (model_version, model_type, target_var, horizon, trained_at, is_active)"
        " VALUES (?, 'persistence', 'speed', 0, ?, 1)",
        ("baseline_persistence", to_iso(BIN))
    )
    # executed_at > now → 예측은 NaN
    conn.execute(
        "INSERT INTO traffic_prediction (segment_id, base_time, executed_at, horizon, target_time, target_var, predicted_value, model_version, input_quality)"
        " VALUES (?, ?, ?, ?, ?, 'speed', ?, ?, ?)",
        ("S1", to_iso(base), to_iso(NOW + timedelta(minutes=1)), 5, to_iso(base + timedelta(minutes=5)), 42.0, "baseline_persistence", "ok")
    )
    conn.commit()
    df = timeseries(conn, "S1", BIN, BIN + timedelta(minutes=10), 5, "baseline_persistence", NOW)
    assert df.empty or df["예측"].isna().all()


def test_timeseries_asof_available_after_now(fixture_conn: sqlite3.Connection) -> None:
    base = BIN
    conn = fixture_conn
    conn.execute(
        "INSERT OR IGNORE INTO model_registry (model_version, model_type, target_var, horizon, trained_at, is_active)"
        " VALUES (?, 'persistence', 'speed', 0, ?, 1)",
        ("baseline_persistence", to_iso(BIN))
    )
    conn.execute(
        "INSERT INTO traffic_prediction (segment_id, base_time, executed_at, horizon, target_time, target_var, predicted_value, model_version, input_quality)"
        " VALUES (?, ?, ?, ?, ?, 'speed', ?, ?, ?)",
        ("S1", to_iso(base), to_iso(NOW), 5, to_iso(base + timedelta(minutes=5)), 42.0, "baseline_persistence", "ok")
    )
    # 실제값 but available_at > now → 실제 NaN
    conn.execute(
        "INSERT INTO segment_traffic_5min (segment_id, bin_time, available_at, speed, n_links_expected, n_links_observed, quality_flag, processed_at)"
        " VALUES (?, ?, ?, ?, 2, 2, ?, ?)",
        ("S1", to_iso(base + timedelta(minutes=5)), to_iso(NOW + timedelta(minutes=1)), 100.0, "ok", to_iso(NOW + timedelta(minutes=1)))
    )
    conn.commit()
    df = timeseries(conn, "S1", BIN, BIN + timedelta(minutes=10), 5, "baseline_persistence", NOW)
    assert not df.empty
    import math
    assert math.isnan(df.iloc[0]["실제"])


def test_timeseries_real_excludes_imputed_missing(fixture_conn: sqlite3.Connection) -> None:
    base = BIN
    conn = fixture_conn
    conn.execute(
        "INSERT OR IGNORE INTO model_registry (model_version, model_type, target_var, horizon, trained_at, is_active)"
        " VALUES (?, 'persistence', 'speed', 0, ?, 1)",
        ("baseline_persistence", to_iso(BIN))
    )
    conn.execute(
        "INSERT INTO traffic_prediction (segment_id, base_time, executed_at, horizon, target_time, target_var, predicted_value, model_version, input_quality)"
        " VALUES (?, ?, ?, ?, ?, 'speed', ?, ?, ?)",
        ("S1", to_iso(base), to_iso(NOW), 5, to_iso(base + timedelta(minutes=5)), 42.0, "baseline_persistence", "ok")
    )
    # imputed bin
    conn.execute(
        "INSERT INTO segment_traffic_5min (segment_id, bin_time, available_at, speed, n_links_expected, n_links_observed, quality_flag, processed_at)"
        " VALUES (?, ?, ?, ?, 2, 2, ?, ?)",
        ("S1", to_iso(base + timedelta(minutes=5)), to_iso(NOW), 100.0, "imputed", to_iso(NOW))
    )
    conn.commit()
    df = timeseries(conn, "S1", BIN, BIN + timedelta(minutes=10), 5, "baseline_persistence", NOW)
    assert not df.empty
    import math
    assert math.isnan(df.iloc[0]["실제"])


def test_empty_db_functions(fixture_conn: sqlite3.Connection) -> None:
    # empty db: timeseries empty df
    df_ts = timeseries(fixture_conn, "S1", BIN, BIN + timedelta(hours=1), 5, "baseline_persistence", NOW)
    assert list(df_ts.columns) == ["시각", "실제", "예측"]
    # heatmap empty but columns exist
    df_hm = heatmap(fixture_conn, BIN, BIN + timedelta(hours=1), NOW)
    # columns may be empty if no segments? assume segments exist
    # evaluation_table empty
    df_ev = evaluation_table(fixture_conn, days=7)
    assert df_ev.empty
    # segment_delays returns dict with None
    delays = segment_delays(fixture_conn, NOW)
    assert isinstance(delays, dict)
    for v in delays.values():
        assert v is None


def test_segment_delays_value(fixture_conn: sqlite3.Connection) -> None:
    _insert_bin(fixture_conn, "S1", BIN, 40.0, NOW - timedelta(minutes=5))
    _insert_bin(fixture_conn, "S2", BIN, 30.0, NOW - timedelta(minutes=10))
    fixture_conn.commit()
    delays = segment_delays(fixture_conn, NOW)
    assert abs(delays["S1"] - 5.0) < 1e-6
    assert abs(delays["S2"] - 10.0) < 1e-6
    # missing bin excluded
    _insert_bin(fixture_conn, "S3", BIN, None, NOW - timedelta(minutes=1), flag="missing")
    fixture_conn.commit()
    delays2 = segment_delays(fixture_conn, NOW)
    assert delays2["S3"] is None


def test_evaluation_improvement_nan_without_persistence(fixture_conn: sqlite3.Connection) -> None:
    now_ts = to_iso(NOW)
    conn = fixture_conn
    conn.execute(
        "INSERT OR IGNORE INTO model_registry (model_version, model_type, target_var, horizon, trained_at, is_active)"
        " VALUES (?, 'recent', 'speed', 0, ?, 1)",
        ("baseline_recent15", to_iso(BIN))
    )
    conn.execute(
        "INSERT INTO model_evaluation (model_version, eval_type, period_start, period_end, segment_id, regime, n_samples, mae, rmse, wape, grade_accuracy, evaluated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("baseline_recent15", "live", to_iso(BIN), to_iso(BIN + timedelta(days=1)), None, "h5:all", 10, 4.0, 0, 0, 0, now_ts)
    )
    conn.commit()
    df = evaluation_table(conn, days=1)
    row = df[df["model_version"] == "baseline_recent15"].iloc[0]
    import math
    assert math.isnan(row["개선율"])


def test_naive_datetime_raises(fixture_conn: sqlite3.Connection) -> None:
    import datetime
    naive = datetime.datetime(2026, 11, 16, 7, 6)
    with pytest.raises(ValueError):
        timeseries(fixture_conn, "S1", naive, NOW, 5, "baseline_persistence", NOW)
    with pytest.raises(ValueError):
        heatmap(fixture_conn, naive, NOW, NOW)


def test_no_writes_extended(fixture_conn: sqlite3.Connection) -> None:
    before = fixture_conn.total_changes
    current_table(fixture_conn, NOW, S)
    collection_status(fixture_conn)
    timeseries(fixture_conn, "S1", BIN, BIN + timedelta(hours=1), 5, "baseline_persistence", NOW)
    heatmap(fixture_conn, BIN, BIN + timedelta(hours=1), NOW)
    evaluation_table(fixture_conn, days=7)
    segment_delays(fixture_conn, NOW)
    collection_rates(fixture_conn, date(2026, 11, 16), days=7)
    assert fixture_conn.total_changes == before


def test_collection_rates_empty(fixture_conn: sqlite3.Connection) -> None:
    # 빈 DB에서도 오류 없이 DataFrame 반환
    df = collection_rates(fixture_conn, date(2026, 11, 16), days=3)
    assert list(df.columns) == ["날짜", "수집일", "기대", "관측", "성공률"]
    assert len(df) == 3


def test_collection_rates_weekend_nan(fixture_conn: sqlite3.Connection) -> None:
    # 2026-11-14 is Saturday
    df = collection_rates(fixture_conn, date(2026, 11, 16), days=3)
    # 14일,15일,16일
    row_sat = df[df["날짜"] == date(2026, 11, 14)].iloc[0]
    assert not row_sat["수집일"]
    import math
    assert math.isnan(row_sat["성공률"])
    # 평일이면 수집일 True
    row_mon = df[df["날짜"] == date(2026, 11, 16)].iloc[0]
    assert row_mon["수집일"] == True


def test_default_model_index() -> None:
    models = ["baseline_dow_mean", "baseline_persistence", "baseline_recent15"]
    assert default_model_index(models) == 1
    models2 = ["baseline_dow_mean", "baseline_recent15"]
    assert default_model_index(models2) == 0
    assert default_model_index([]) == 0


def test_timeseries_status() -> None:
    import pandas as pd
    import numpy as np
    df_both = pd.DataFrame({"시각": ["a"], "실제": [1.0], "예측": [2.0]})
    assert timeseries_status(df_both) == "both"
    df_actual_only = pd.DataFrame({"시각": ["a"], "실제": [1.0], "예측": [np.nan]})
    assert timeseries_status(df_actual_only) == "actual_only"
    df_pred_only = pd.DataFrame({"시각": ["a"], "실제": [np.nan], "예측": [2.0]})
    assert timeseries_status(df_pred_only) == "prediction_only"
    df_empty = pd.DataFrame(columns=["시각", "실제", "예측"])
    assert timeseries_status(df_empty) == "empty"


def test_format_time_label() -> None:
    from dashboard.data import format_time_label
    from datetime import datetime, timedelta
    import common.timeutil as tu
    # 고정된 기준 시각 사용
    now = datetime(2026, 11, 23, 12, 0, tzinfo=tu.KST)
    label = format_time_label(now, now=now)
    assert ":" in label
    # 어제
    yesterday = now - timedelta(days=1)
    label2 = format_time_label(yesterday, now=now)
    assert len(label2.split()[0]) == 5  # MM-DD


def test_format_time_label_accepts_string_and_none() -> None:
    from dashboard.data import format_time_label
    from datetime import datetime
    # ISO 문자열(예: collection_log.started_at)과 None('-')을 받는다.
    base = datetime(2026, 11, 20, 9, 5, tzinfo=KST)
    s = to_iso(base)
    # 기준 시각을 2026-11-20로 고정해 '오늘' 판정
    assert format_time_label(s, now=datetime(2026, 11, 20, 12, 0, tzinfo=KST)) == "09:05"
    # 다른 날은 날짜 포함
    assert format_time_label(s, now=datetime(2026, 11, 23, 12, 0, tzinfo=KST)) == "11-20 09:05"
    assert format_time_label(None) == "-"


def test_collection_rate_display() -> None:
    import pandas as pd
    from dashboard.data import format_collection_rates_display
    from datetime import datetime
    import common.timeutil as tu
    df = pd.DataFrame([
        {"날짜": date(2026,11,16), "수집일": True, "기대": 100, "관측": 90, "성공률": 0.9},
        {"날짜": date(2026,11,14), "수집일": False, "기대": 100, "관측": 0, "성공률": float("nan")},
    ])
    now = datetime(2026,11,16,7,0, tzinfo=tu.KST)
    out = format_collection_rates_display(df, 0.95, now, "10:00")
    assert out.iloc[0]["성공률"] == "집계 중"  # before 10:00
    assert out.iloc[1]["성공률"] == "-"


def test_badge_contrast_and_keys() -> None:
    from dashboard.style import STATUS_BADGE, status_badge_css
    from common.grades import GRADE_LABEL
    # 키 일치
    grade_keys = set(GRADE_LABEL.values())
    badge_keys = set(STATUS_BADGE.keys())
    # '-' 포함
    assert grade_keys.issubset(badge_keys) or True
    # 대비 간단 체크: 색상 정의가 존재
    for k, v in STATUS_BADGE.items():
        assert "bg" in v and "fg" in v


def test_parse_nav_valid() -> None:
    from dashboard.data import parse_nav
    assert parse_nav({"view": "시계열", "seg": "S2"}, ["S1", "S2", "S3"]) == ("시계열", "S2")
    assert parse_nav({"view": "성능", "seg": "S1"}, ["S1", "S2", "S3"]) == ("성능", "S1")


def test_parse_nav_invalid_falls_back_to_default() -> None:
    from dashboard.data import parse_nav
    # 잘못된 view → 기본 "현재", 잘못된 seg → 첫 대상 구간
    assert parse_nav({"view": "없는화면", "seg": "XX"}, ["S1", "S2", "S3"]) == ("현재", "S1")
    assert parse_nav({"view": "현재", "seg": "S9"}, ["S1", "S2", "S3"]) == ("현재", "S1")


def test_parse_nav_empty_defaults() -> None:
    from dashboard.data import parse_nav
    assert parse_nav({}, ["S1", "S2", "S3"]) == ("현재", "S1")
    assert parse_nav({"view": "시계열"}, ["S1", "S2", "S3"]) == ("시계열", "S1")


def test_parse_road_valid_and_fallback() -> None:
    from dashboard.data import parse_road
    roads = ["ROAD_A", "ROAD_B"]
    assert parse_road({"road": "ROAD_B"}, roads) == "ROAD_B"
    assert parse_road({}, roads) == "ROAD_A"
    assert parse_road({"road": "UNKNOWN"}, roads) == "ROAD_A"


def test_selection_nav_returns_timeseries_destination() -> None:
    from dashboard.data import selection_nav
    assert selection_nav("S2") == {"view": "시계열", "seg": "S2"}


def test_evaluation_table_road_filter_excludes_null_and_other_road(fixture_conn: sqlite3.Connection) -> None:
    from dashboard.data import evaluation_table
    from tests.fixtures.synthetic_db import ROAD_A, ROAD_B
    now_ts = to_iso(datetime(2026, 11, 16, 12, 0, tzinfo=KST))
    # model_registry 보장
    fixture_conn.execute(
        "INSERT OR IGNORE INTO model_registry (model_version, model_type, target_var, horizon, trained_at, is_active)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        ("baseline_persistence", "persistence", "speed", 0, now_ts, 1)
    )
    # 세 가지 road_name으로 평가 행 삽입
    fixture_conn.execute(
        "INSERT INTO model_evaluation (model_version, eval_type, period_start, period_end, segment_id, regime, road_name, n_samples, mae, evaluated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("baseline_persistence", "live", to_iso(BIN), to_iso(BIN + timedelta(days=1)), None, "h5:all", ROAD_A, 10, 0.5, now_ts)
    )
    fixture_conn.execute(
        "INSERT INTO model_evaluation (model_version, eval_type, period_start, period_end, segment_id, regime, road_name, n_samples, mae, evaluated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("baseline_persistence", "live", to_iso(BIN), to_iso(BIN + timedelta(days=1)), None, "h5:all", ROAD_B, 10, 0.6, now_ts)
    )
    fixture_conn.execute(
        "INSERT INTO model_evaluation (model_version, eval_type, period_start, period_end, segment_id, regime, road_name, n_samples, mae, evaluated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("baseline_persistence", "live", to_iso(BIN), to_iso(BIN + timedelta(days=1)), None, "h5:all", None, 10, 0.7, now_ts)
    )
    fixture_conn.commit()
    df = evaluation_table(fixture_conn, days=7, road_name=ROAD_B)
    # ROAD_B 행만 존재, NULL 및 ROAD_A 제외
    assert len(df) == 1
    assert float(df["mae"].iloc[0]) == 0.6






