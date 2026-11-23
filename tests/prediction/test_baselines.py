"""D-ML-01 기준 모델 recent15·dow_mean 테스트 (C-04 v1).

synthetic: 모든 값은 테스트가 직접 넣는 합성 값이다. 여기서 나온 수치를 실제 성능으로 보고하지 않는다.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from common.timeutil import to_iso
from config.settings import Settings
from prediction import backfill_actuals, predict_latest
from prediction.baseline import DOW_MEAN_VERSION, PERSISTENCE_VERSION, RECENT15_VERSION
from tests.fixtures.synthetic_db import ROAD_A, ROAD_B, build_fixture_db
from tests.prediction.helpers import insert_bin, t

NOW = t(16, 7, 6)  # 2026-11-16 월요일 07:06
BASE = t(16, 7, 0)

# horizon별 target_time의 HH:MM (5·10·15·30분)
TARGET_HHMM = [(7, 5), (7, 10), (7, 15), (7, 30)]


def _preds(
    conn: sqlite3.Connection, model_version: str, segment_id: str = "S1"
) -> dict[int, sqlite3.Row]:
    rows = conn.execute(
        "SELECT * FROM traffic_prediction WHERE segment_id = ? AND model_version = ? ORDER BY horizon",
        (segment_id, model_version),
    ).fetchall()
    return {r["horizon"]: r for r in rows}


def test_registry_has_three_baselines(fixture_conn: sqlite3.Connection) -> None:
    predict_latest(NOW, conn=fixture_conn)
    rows = {r["model_version"]: r for r in fixture_conn.execute("SELECT * FROM model_registry")}
    assert set(rows) == {PERSISTENCE_VERSION, RECENT15_VERSION, DOW_MEAN_VERSION}
    assert rows[PERSISTENCE_VERSION]["model_type"] == "baseline_persistence"
    assert rows[RECENT15_VERSION]["model_type"] == "baseline_recent15"
    assert rows[DOW_MEAN_VERSION]["model_type"] == "baseline_dow_mean"
    for r in rows.values():
        assert r["target_var"] == "speed"
        assert r["horizon"] == 0
        assert r["is_active"] == 1
        assert r["trained_at"] == to_iso(NOW)


def test_three_models_share_base_time(fixture_conn: sqlite3.Connection) -> None:
    insert_bin(fixture_conn, "S1", BASE, 45.0)
    predict_latest(NOW, conn=fixture_conn)
    base_times = {
        r[0]
        for r in fixture_conn.execute(
            "SELECT DISTINCT base_time FROM traffic_prediction WHERE segment_id = 'S1'"
        )
    }
    assert base_times == {to_iso(BASE)}
    for model in (PERSISTENCE_VERSION, RECENT15_VERSION, DOW_MEAN_VERSION):
        assert set(_preds(fixture_conn, model)) == {5, 10, 15, 30}


def test_target_segment_order_corridors(fixture_conn_two: sqlite3.Connection) -> None:
    # 예측 대상 구간 순서는 (settings.corridors 도로 순서, seq)다 (C-01 v1.4).
    from prediction.baseline import ordered_target_segments

    # corridors에 픽스처 도로를 거꾸로 넣으면 W가 먼저다
    assert ordered_target_segments(
        fixture_conn_two, Settings(corridors=(ROAD_B, ROAD_A))
    ) == ["W1", "W2", "S1", "S2", "S3"]
    # corridors 순서대로면 S가 먼저다
    assert ordered_target_segments(
        fixture_conn_two, Settings(corridors=(ROAD_A, ROAD_B))
    ) == ["S1", "S2", "S3", "W1", "W2"]


def test_target_segment_order_unknown_roads_by_name(fixture_conn_two: sqlite3.Connection) -> None:
    # corridors에 없는 도로는 목록에 있는 도로 뒤에 road_name 순으로 온다 (C-01 v1.4).
    # 기본 corridors(창원대로, 원이대로)엔 합성 도로가 없으므로 road_name 순: 합성도로 < 합성도로B.
    from prediction.baseline import ordered_target_segments

    assert ordered_target_segments(fixture_conn_two, Settings()) == [
        "S1",
        "S2",
        "S3",
        "W1",
        "W2",
    ]


def test_predict_inserts_in_road_order(
    fixture_conn_two: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    # corridors 순서를 뒤집으면 첫 예측 행은 두 번째 도로의 첫 구간(W1)에서 나온다.
    _with_settings(monkeypatch, corridors=(ROAD_B, ROAD_A))
    predict_latest(NOW, conn=fixture_conn_two)
    first = fixture_conn_two.execute(
        "SELECT segment_id FROM traffic_prediction ORDER BY id LIMIT 1"
    ).fetchone()
    assert first[0] == "W1"


def test_second_road_not_target_no_predictions(tmp_path) -> None:
    # 두 번째 도로가 대상이 아니면(second_road_target=False → W is_target=0) W 예측 행이 없다
    # (Review Focus 3: target_corridors에 없는 도로가 예측에 새지 않는다).
    db = build_fixture_db(tmp_path / "w_off.db", second_road=True, second_road_target=False)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        n = predict_latest(NOW, conn=conn)
        assert n == 36  # 대상 3구간(S1~S3) x horizon 4 x 모델 3
        segs = {r[0] for r in conn.execute("SELECT DISTINCT segment_id FROM traffic_prediction")}
        assert segs == {"S1", "S2", "S3"}  # W0~W2는 예측 대상이 아니다
    finally:
        conn.close()


def test_imputed_input_degraded(fixture_conn: sqlite3.Connection) -> None:
    # forward fill로 채운 bin은 실제 관측이 아니다 → 예측 입력으로는 degraded (C-04).
    insert_bin(fixture_conn, "S1", BASE, 45.0, flag="imputed", is_imputed=1)
    predict_latest(NOW, conn=fixture_conn)
    persistence = _preds(fixture_conn, PERSISTENCE_VERSION)
    assert len(persistence) == 4
    for r in persistence.values():
        assert r["predicted_value"] == pytest.approx(45.0)
        assert r["input_quality"] == "degraded"


def test_recent15_mean(fixture_conn: sqlite3.Connection) -> None:
    insert_bin(fixture_conn, "S1", t(16, 6, 50), 45.0)
    insert_bin(fixture_conn, "S1", t(16, 6, 55), 50.0)
    insert_bin(fixture_conn, "S1", BASE, 55.0)
    predict_latest(NOW, conn=fixture_conn)

    recent = _preds(fixture_conn, RECENT15_VERSION)
    assert len(recent) == 4
    for r in recent.values():
        assert r["predicted_value"] == pytest.approx(50.0)  # (45+50+55)/3
        assert r["input_quality"] == "ok"
        assert r["base_time"] == to_iso(BASE)


def test_recent15_imputed_degraded(fixture_conn: sqlite3.Connection) -> None:
    # 평균의 근거 bin 중 imputed(보정값)가 섞이면 degraded다 (C-04 입력 품질).
    insert_bin(fixture_conn, "S1", t(16, 6, 50), 45.0)
    insert_bin(fixture_conn, "S1", t(16, 6, 55), 50.0, flag="imputed", is_imputed=1)
    insert_bin(fixture_conn, "S1", BASE, 55.0)
    predict_latest(NOW, conn=fixture_conn)

    recent = _preds(fixture_conn, RECENT15_VERSION)
    assert len(recent) == 4
    for r in recent.values():
        assert r["predicted_value"] == pytest.approx(50.0)  # (45+50+55)/3, 보정값도 값으로는 쓴다
        assert r["input_quality"] == "degraded"


def test_recent15_needs_two(fixture_conn: sqlite3.Connection) -> None:
    # S1: 값이 1개뿐 → skipped
    insert_bin(fixture_conn, "S1", t(16, 6, 55), None, flag="missing", available_at=t(16, 7, 0))
    insert_bin(fixture_conn, "S1", BASE, 45.0)
    # S2: 값이 2개 → 평균
    insert_bin(fixture_conn, "S2", t(16, 6, 55), 40.0)
    insert_bin(fixture_conn, "S2", BASE, 50.0)

    predict_latest(NOW, conn=fixture_conn)

    s1 = _preds(fixture_conn, RECENT15_VERSION, "S1")
    assert len(s1) == 4
    for r in s1.values():
        assert r["predicted_value"] is None
        assert r["input_quality"] == "skipped"

    s2 = _preds(fixture_conn, RECENT15_VERSION, "S2")
    assert len(s2) == 4
    for r in s2.values():
        assert r["predicted_value"] == pytest.approx(45.0)
        assert r["input_quality"] == "ok"


def test_recent15_uses_past_only(fixture_conn: sqlite3.Connection) -> None:
    # available_at이 now보다 늦은 bin은 쓰지 않는다 (미래 정보 금지).
    insert_bin(fixture_conn, "S1", t(16, 6, 55), 40.0, available_at=t(16, 7, 0))
    insert_bin(fixture_conn, "S1", BASE, 50.0, available_at=t(16, 7, 5, 40))
    insert_bin(fixture_conn, "S1", t(16, 7, 5), 999.0, available_at=t(16, 7, 10))
    predict_latest(NOW, conn=fixture_conn)

    recent = _preds(fixture_conn, RECENT15_VERSION)
    for r in recent.values():
        assert r["predicted_value"] == pytest.approx(45.0)  # (40+50)/2, 999는 아직 사용 불가
        assert r["base_time"] == to_iso(BASE)


def test_dow_mean_needs_three_weeks(fixture_conn: sqlite3.Connection) -> None:
    # 같은 월요일·같은 HH:MM 값이 2주치뿐 → skipped (11-02, 11-09는 모두 월요일)
    for day, value in [(2, 40.0), (9, 50.0)]:
        for hour, minute in TARGET_HHMM:
            insert_bin(fixture_conn, "S1", t(day, hour, minute), value)

    predict_latest(NOW, conn=fixture_conn)
    dow = _preds(fixture_conn, DOW_MEAN_VERSION)
    assert len(dow) == 4
    for r in dow.values():
        assert r["predicted_value"] is None
        assert r["input_quality"] == "skipped"

    # 세 번째 주(10-26, 월요일)가 들어오면 skipped 행을 덮어쓴다 (같은 base_time 키).
    for hour, minute in TARGET_HHMM:
        insert_bin(fixture_conn, "S1", t(26, hour, minute, month=10), 60.0)
    n = predict_latest(NOW, conn=fixture_conn)
    assert n == 4  # S1 dow_mean 4행만 갱신
    dow = _preds(fixture_conn, DOW_MEAN_VERSION)
    for r in dow.values():
        assert r["predicted_value"] == pytest.approx(50.0)  # (40+50+60)/3
        assert r["input_quality"] == "ok"


def test_dow_mean_value(fixture_conn: sqlite3.Connection) -> None:
    # now 이전 4주치 월요일(10-19·10-26·11-02·11-09) 07:15 값
    # + imputed 1개(제외) + 아직 사용할 수 없는 당일 값(제외)
    for month, day, value in [(10, 19, 30.0), (10, 26, 40.0), (11, 2, 50.0), (11, 9, 60.0)]:
        insert_bin(fixture_conn, "S1", t(day, 7, 15, month=month), value)
    insert_bin(fixture_conn, "S1", t(12, 7, 15, month=10), 200.0, flag="imputed", is_imputed=1)
    insert_bin(fixture_conn, "S1", t(16, 7, 15), 999.0, available_at=t(16, 8, 0))

    predict_latest(NOW, conn=fixture_conn)
    dow = _preds(fixture_conn, DOW_MEAN_VERSION)
    assert dow[15]["predicted_value"] == pytest.approx(45.0)  # (30+40+50+60)/4, imputed 제외
    assert dow[15]["input_quality"] == "ok"
    assert dow[15]["base_time"] == to_iso(BASE)
    assert dow[15]["target_time"] == to_iso(t(16, 7, 15))
    for h in (5, 10, 30):  # 다른 HH:MM은 표본이 없다
        assert dow[h]["predicted_value"] is None
        assert dow[h]["input_quality"] == "skipped"


def _with_settings(monkeypatch: pytest.MonkeyPatch, **changes: object) -> None:
    """predict_latest가 쓰는 get_settings를 지정 값으로 바꾼다(C-06 시그니처에 settings 인자가 없다)."""
    monkeypatch.setattr("prediction.get_settings", lambda: replace(Settings(), **changes))


def test_dow_mean_lookback_follows_setting(
    fixture_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    # dow_mean 조회 하한은 settings.dow_mean_lookback_weeks를 따른다 (C-04 v1.3). 3주로 줄인다.
    _with_settings(monkeypatch, dow_mean_lookback_weeks=3)
    # 모두 2026년 월요일 07:15. base_time − 3주 = 10-26 07:00 → 10-19(4주 전)는 하한 밖.
    for month, day, value in [(10, 19, 200.0), (10, 26, 30.0), (11, 2, 40.0), (11, 9, 50.0)]:
        insert_bin(fixture_conn, "S1", t(day, 7, 15, month=month), value)
    # S2: 하한 안 2주(10-26, 11-09) + 하한 밖 1주(10-12) → 3주로 세면 안 된다
    for month, day, value in [(10, 12, 60.0), (10, 26, 40.0), (11, 9, 50.0)]:
        insert_bin(fixture_conn, "S2", t(day, 7, 15, month=month), value)

    predict_latest(NOW, conn=fixture_conn)
    s1 = _preds(fixture_conn, DOW_MEAN_VERSION, "S1")
    assert s1[15]["predicted_value"] == pytest.approx(40.0)  # (30+40+50)/3, 10-19 제외
    assert s1[15]["input_quality"] == "ok"
    s2 = _preds(fixture_conn, DOW_MEAN_VERSION, "S2")
    assert s2[15]["predicted_value"] is None  # 하한 안 2주뿐 → skipped
    assert s2[15]["input_quality"] == "skipped"


def test_dow_mean_boundary_inclusive(
    fixture_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 경계 bin(정확히 base_time − dow_mean_lookback_weeks주)은 포함된다(`>=`).
    # 경계 순간의 HH:MM은 base_time과 같으므로, target과 HH:MM이 같아지는 horizon 0으로 검증한다.
    _with_settings(monkeypatch, horizons=(0,))
    # 모두 2026년 월요일 07:00: 09-14는 9주 전(제외), 09-21은 정확히 8주 전(경계, 포함).
    for month, day, value in [(9, 14, 200.0), (9, 21, 60.0), (10, 5, 30.0), (10, 12, 40.0)]:
        insert_bin(fixture_conn, "S1", t(day, 7, 0, month=month), value)

    predict_latest(NOW, conn=fixture_conn)
    s1 = _preds(fixture_conn, DOW_MEAN_VERSION, "S1")
    assert s1[0]["predicted_value"] == pytest.approx(130.0 / 3.0)  # (60+30+40)/3, 경계 포함
    assert s1[0]["input_quality"] == "ok"  # 경계가 빠지면 2주라 skipped가 된다


def test_dow_mean_rejects_horizons_24h_apart(
    fixture_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    # target을 HH:MM 문자열로 묶어 표본을 모으므로, horizon 간 차이가 24시간 이상이면
    # (같은 HH:MM이 다른 요일 target이 되면) 오류로 막는다.
    _with_settings(monkeypatch, horizons=(5, 5 + 24 * 60))

    with pytest.raises(ValueError, match="24시간"):
        predict_latest(NOW, conn=fixture_conn)
    # 예외 시 rollback되어 저장된 행이 없어야 한다
    assert fixture_conn.execute("SELECT COUNT(*) FROM traffic_prediction").fetchone()[0] == 0


def test_skipped_overwritten_by_late_bin(fixture_conn: sqlite3.Connection) -> None:
    first = predict_latest(NOW, conn=fixture_conn)
    assert first == 36  # 대상 3구간 x horizon 4 x 모델 3

    # S1 07:00 bin이 늦게 도착 → skipped 행을 덮어쓴다
    insert_bin(fixture_conn, "S1", BASE, 45.0, available_at=t(16, 7, 5, 40))
    n = predict_latest(t(16, 7, 7), conn=fixture_conn)
    assert n == 4  # persistence 4행만 갱신 (recent15는 값 1개, dow_mean은 3주 미만)
    persistence = _preds(fixture_conn, PERSISTENCE_VERSION)
    for r in persistence.values():
        assert r["predicted_value"] == pytest.approx(45.0)
        assert r["input_quality"] == "ok"
        assert r["executed_at"] == to_iso(t(16, 7, 7))

    # 정상 예측(ok)은 나중 bin 값이 바뀌어도 덮어쓰지 않는다
    fixture_conn.execute(
        "UPDATE segment_traffic_5min SET speed = 30.0 WHERE segment_id = 'S1' AND bin_time = ?",
        (to_iso(BASE),),
    )
    fixture_conn.commit()
    n = predict_latest(t(16, 7, 8), conn=fixture_conn)
    assert n == 0
    persistence = _preds(fixture_conn, PERSISTENCE_VERSION)
    assert all(r["predicted_value"] == pytest.approx(45.0) for r in persistence.values())


def test_backfill_window(fixture_conn: sqlite3.Connection) -> None:
    insert_bin(fixture_conn, "S1", BASE, 45.0)
    predict_latest(NOW, conn=fixture_conn)
    for minute in (5, 10, 15, 30):
        target = t(16, 7, minute)
        insert_bin(fixture_conn, "S1", target, 40.0, available_at=t(16, 7, minute, 40))

    # 13:07 기준 6시간 경계: 07:05는 제외, 07:10부터 포함
    n = backfill_actuals(t(16, 13, 7), conn=fixture_conn)
    assert n == 9  # target 07:10·07:15·07:30 x 모델 3
    persistence = _preds(fixture_conn, PERSISTENCE_VERSION)
    assert persistence[5]["actual_value"] is None  # 07:05는 now-6h보다 이전
    for h in (10, 15, 30):
        assert persistence[h]["actual_value"] == pytest.approx(40.0)


def test_backfill_skips_imputed(fixture_conn: sqlite3.Connection) -> None:
    insert_bin(fixture_conn, "S1", BASE, 45.0)
    predict_latest(NOW, conn=fixture_conn)
    # imputed·missing은 실제값이 아니다 (C-04 backfill 규칙)
    insert_bin(fixture_conn, "S1", t(16, 7, 10), 40.0, flag="imputed", is_imputed=1)
    insert_bin(fixture_conn, "S1", t(16, 7, 15), 35.0, flag="missing")
    insert_bin(fixture_conn, "S1", t(16, 7, 30), 30.0)

    n = backfill_actuals(t(16, 7, 40), conn=fixture_conn)
    assert n == 3  # 07:30 target x 모델 3
    persistence = _preds(fixture_conn, PERSISTENCE_VERSION)
    assert persistence[10]["actual_value"] is None
    assert persistence[15]["actual_value"] is None
    assert persistence[30]["actual_value"] == pytest.approx(30.0)
    assert persistence[30]["abs_error"] == pytest.approx(15.0)
