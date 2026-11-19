"""preprocessing.run 5분 구간 집계 테스트 (D-DAT-02a, D-DAT-02b). 입력은 합성 픽스처다(synthetic)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from common.timeutil import KST, parse_iso, to_iso
from preprocessing import run
from tests.fixtures.synthetic_db import fixture_speed

UNTIL = datetime(2026, 11, 16, 8, 0, 30, tzinfo=KST)
LOOKBACK = 90


def _t(hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime(2026, 11, 16, hh, mm, ss, tzinfo=KST)


def _row(conn: sqlite3.Connection, sid: str, bin_time: datetime) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM segment_traffic_5min WHERE segment_id = ? AND bin_time = ?", (sid, to_iso(bin_time))
    ).fetchone()


def _harmonic(lengths: list[float], speeds: list[float]) -> float:
    return sum(lengths) / sum(l / v for l, v in zip(lengths, speeds))


def _add_obs(conn: sqlite3.Connection, link_id: str, ts: datetime, collected: datetime, speed: float | None,
             flag: str = "ok") -> None:
    conn.execute(
        "INSERT INTO traffic_observation (source, link_id, source_timestamp, collected_at, speed, quality_flag)"
        " VALUES ('synthetic', ?, ?, ?, ?, ?)",
        (link_id, to_iso(ts), to_iso(collected), speed, flag),
    )
    conn.commit()


def test_harmonic_mean_s1(fixture_conn: sqlite3.Connection) -> None:
    run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)
    r = _row(fixture_conn, "S1", _t(6, 30))
    v1, v2 = fixture_speed("SYN0000001", _t(6, 30)), fixture_speed("SYN0000002", _t(6, 30))
    assert r["speed"] == pytest.approx(1200 / (500 / v1 + 700 / v2))
    assert r["quality_flag"] == "ok"
    assert (r["n_links_expected"], r["n_links_observed"]) == (2, 2)
    assert r["is_imputed"] == 0
    assert r["speed_side"] is None
    assert r["available_at"] == to_iso(_t(6, 30, 40))
    assert r["processed_at"] == to_iso(UNTIL)


def test_flagged_excluded(fixture_conn: sqlite3.Connection) -> None:
    run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)
    prev = _row(fixture_conn, "S1", _t(7, 5))
    r = _row(fixture_conn, "S1", _t(7, 10))
    # SYN0000002가 default_value(0)라 관측 길이 500/1200 = 41.7% < partial_min_coverage(0.7) → missing.
    # 직전 07:05 bin이 실제 값이라 짧은 결측 보정으로 그 값이 채워진다(imputed, is_imputed=1).
    # Slice 0에서는 1개만 관측돼도 partial이었으므로 기대값을 규칙 변경(D-DAT-02b)에 맞춰 갱신했다.
    assert prev["quality_flag"] == "ok"
    assert r["quality_flag"] == "imputed"
    assert r["is_imputed"] == 1
    assert r["speed"] == pytest.approx(prev["speed"])
    assert r["speed"] == pytest.approx(_harmonic([500, 700], [fixture_speed("SYN0000001", _t(7, 5)),
                                                             fixture_speed("SYN0000002", _t(7, 5))]))
    assert r["speed"] != 0
    assert (r["n_links_expected"], r["n_links_observed"]) == (2, 1)
    assert r["available_at"] == to_iso(_t(7, 15))  # imputed는 bin 끝 시각


def test_out_of_range_excluded(fixture_conn: sqlite3.Connection) -> None:
    run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)
    prev = _row(fixture_conn, "S3", _t(7, 10))
    r = _row(fixture_conn, "S3", _t(7, 15))  # SYN0000004 out_of_range(200) → 길이 NULL인 SYN0000005만 남음
    # 관측 1/2 = 50% < 70% → missing, 직전 07:10 bin(단순 평균 48.5)이 실제 값이라 imputed가 된다.
    # 200은 어디에도 쓰이지 않는다(쓰이면 123.5가 된다).
    assert prev["quality_flag"] == "unweighted"
    assert r["quality_flag"] == "imputed"
    assert r["is_imputed"] == 1
    assert r["speed"] == pytest.approx(prev["speed"])
    assert r["speed"] < 100.0
    assert r["n_links_observed"] == 1


def test_missing_not_zero(fixture_conn: sqlite3.Connection) -> None:
    run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)
    # S2 갭(07:20~07:40)의 3번째 결측 bin. 앞 2개(07:20·07:25)는 imputed이고 3번째부터 채우지 않는다.
    r = _row(fixture_conn, "S2", _t(7, 30))
    assert r["speed"] is None
    assert r["quality_flag"] == "missing"
    assert r["is_imputed"] == 0
    assert (r["n_links_expected"], r["n_links_observed"]) == (1, 0)
    assert r["available_at"] == to_iso(_t(7, 35))  # bin 끝 시각


def test_unweighted_s3(fixture_conn: sqlite3.Connection) -> None:
    run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)
    r = _row(fixture_conn, "S3", _t(6, 30))
    v4, v5 = fixture_speed("SYN0000004", _t(6, 30)), fixture_speed("SYN0000005", _t(6, 30))
    assert r["speed"] == pytest.approx((v4 + v5) / 2)
    assert r["quality_flag"] == "unweighted"


def test_row_count_and_bins(fixture_conn: sqlite3.Connection) -> None:
    n = run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)
    assert n == 18 * 4  # 06:30~07:55 bin 18개 x 구간 4개
    bins = [r[0] for r in fixture_conn.execute("SELECT DISTINCT bin_time FROM segment_traffic_5min ORDER BY 1")]
    assert bins[0] == to_iso(_t(6, 30)) and bins[-1] == to_iso(_t(7, 55))


def test_no_future_data(fixture_conn: sqlite3.Connection) -> None:
    until = _t(7, 0, 30)
    # 06:55 bin 안의 더 늦은 관측이지만 until 이후에 수집됨 → 쓰면 안 된다
    _add_obs(fixture_conn, "SYN0000001", _t(6, 57), _t(7, 1), 10.0)
    run(until, conn=fixture_conn, lookback_minutes=LOOKBACK)

    assert _row(fixture_conn, "S1", _t(7, 0)) is None  # 07:05에 끝나므로 미완성
    r = _row(fixture_conn, "S1", _t(6, 55))
    v1, v2 = fixture_speed("SYN0000001", _t(6, 55)), fixture_speed("SYN0000002", _t(6, 55))
    assert r["speed"] == pytest.approx(_harmonic([500, 700], [v1, v2]))
    for row in fixture_conn.execute("SELECT available_at, processed_at FROM segment_traffic_5min"):
        assert parse_iso(row["available_at"]) <= until
        assert row["processed_at"] == to_iso(until)


def test_available_at_never_after_until(fixture_conn: sqlite3.Connection) -> None:
    run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)
    rows = fixture_conn.execute("SELECT bin_time, available_at, quality_flag FROM segment_traffic_5min").fetchall()
    assert any(r["quality_flag"] == "missing" for r in rows)
    for r in rows:
        assert parse_iso(r["available_at"]) <= UNTIL
        assert parse_iso(r["available_at"]) >= parse_iso(r["bin_time"])


def test_latest_ok_observation_in_bin(fixture_conn: sqlite3.Connection) -> None:
    # 06:30 bin에 SYN0000001 관측 추가: 06:33 ok(30), 06:34 default_value(0)
    _add_obs(fixture_conn, "SYN0000001", _t(6, 33), _t(6, 33, 40), 30.0)
    _add_obs(fixture_conn, "SYN0000001", _t(6, 34), _t(6, 34, 40), 0.0, "default_value")
    run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)
    r = _row(fixture_conn, "S1", _t(6, 30))
    v2 = fixture_speed("SYN0000002", _t(6, 30))
    assert r["speed"] == pytest.approx(_harmonic([500, 700], [30.0, v2]))
    assert r["available_at"] == to_iso(_t(6, 33, 40))


def test_side_link_not_mixed(fixture_conn: sqlite3.Connection) -> None:
    # 실제 segment_links.csv처럼 측도(is_mainline=0) 링크가 있는 구간
    fixture_conn.execute(
        "INSERT INTO segment_link (segment_id, link_id, source, seq, link_length_m, is_mainline, nodelink_ver, valid_from)"
        " VALUES ('S1', 'SYN0000009', 'synthetic', 3, 300.0, 0, 'synthetic', '2026-01-01T00:00:00+09:00')"
    )
    fixture_conn.commit()
    _add_obs(fixture_conn, "SYN0000009", _t(6, 30), _t(6, 30, 40), 5.0)
    run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)
    r = _row(fixture_conn, "S1", _t(6, 30))
    v1, v2 = fixture_speed("SYN0000001", _t(6, 30)), fixture_speed("SYN0000002", _t(6, 30))
    assert r["speed"] == pytest.approx(_harmonic([500, 700], [v1, v2]))
    assert r["quality_flag"] == "ok"
    assert (r["n_links_expected"], r["n_links_observed"]) == (2, 2)
    # 측도 링크 관측은 본선 집계에 섞이지 않고 speed_side로만 나간다.
    assert r["speed_side"] == pytest.approx(5.0)


def test_link_validity_window(fixture_conn: sqlite3.Connection) -> None:
    # SYN0000002가 07:00부터 무효 → 07:00 이후 S1은 SYN0000001 하나만 기대
    fixture_conn.execute(
        "UPDATE segment_link SET valid_to = ? WHERE link_id = 'SYN0000002'", (to_iso(_t(7, 0)),)
    )
    fixture_conn.commit()
    run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)
    before, after = _row(fixture_conn, "S1", _t(6, 55)), _row(fixture_conn, "S1", _t(7, 0))
    assert before["n_links_expected"] == 2
    assert after["n_links_expected"] == 1
    assert after["quality_flag"] == "ok"
    assert after["speed"] == pytest.approx(fixture_speed("SYN0000001", _t(7, 0)))


def test_ok_zero_speed_excluded_with_warning(
    fixture_conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    # 수집기 플래그 오류를 흉내 낸 행: quality_flag='ok'인데 speed=0
    _add_obs(fixture_conn, "SYN0000003", _t(7, 25), _t(7, 25, 40), 0.0)  # 갭 구간 → 다른 관측 없음
    _add_obs(fixture_conn, "SYN0000002", _t(6, 31), _t(6, 31, 40), 0.0)  # 06:30 관측보다 늦은 0
    with caplog.at_level("WARNING", logger="traffic.preprocessing.aggregate"):
        n = run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)
    assert n == 72

    gap = _row(fixture_conn, "S2", _t(7, 25))
    # speed=0 관측은 빠졌으므로 이 bin은 관측 없음(41.7%가 아니라 0%). 갭의 2번째 결측 bin이라
    # 직전 실제 값(07:15)으로 짧은 결측 보정이 된다. 0으로 채워진 것이 아니다.
    assert gap["quality_flag"] == "imputed" and gap["is_imputed"] == 1
    assert gap["speed"] == pytest.approx(fixture_speed("SYN0000003", _t(7, 15)))
    assert gap["n_links_observed"] == 0

    s1 = _row(fixture_conn, "S1", _t(6, 30))
    v1, v2 = fixture_speed("SYN0000001", _t(6, 30)), fixture_speed("SYN0000002", _t(6, 30))
    assert s1["speed"] == pytest.approx(_harmonic([500, 700], [v1, v2]))
    assert s1["available_at"] == to_iso(_t(6, 30, 40))

    msgs = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("SYN0000003" in m and to_iso(_t(7, 25)) in m for m in msgs)
    assert any("SYN0000002" in m and to_iso(_t(6, 31)) in m for m in msgs)


@pytest.mark.parametrize(
    ("lookback", "expected_bins"),
    [(7, [(7, 55)]), (5, [(7, 55)]), (10, [(7, 50), (7, 55)]), (12, [(7, 50), (7, 55)]), (4, [])],
)
def test_window_not_wider_than_lookback(
    fixture_conn: sqlite3.Connection, lookback: int, expected_bins: list[tuple[int, int]]
) -> None:
    n = run(UNTIL, conn=fixture_conn, lookback_minutes=lookback)  # until=08:00:30
    bins = [r[0] for r in fixture_conn.execute("SELECT DISTINCT bin_time FROM segment_traffic_5min ORDER BY 1")]
    assert bins == [to_iso(_t(h, m)) for h, m in expected_bins]
    assert n == len(expected_bins) * 4


def test_idempotent(fixture_conn: sqlite3.Connection) -> None:
    n1 = run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)
    c1 = fixture_conn.execute("SELECT COUNT(*) FROM segment_traffic_5min").fetchone()[0]
    n2 = run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)
    c2 = fixture_conn.execute("SELECT COUNT(*) FROM segment_traffic_5min").fetchone()[0]
    assert n1 == n2 == c1 == c2


def test_naive_rejected(fixture_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        run(datetime(2026, 11, 16, 8, 0, 30), conn=fixture_conn)


def test_conn_none_uses_default_db(fixture_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_PATH", str(fixture_db))
    assert run(UNTIL, lookback_minutes=LOOKBACK) == 72
    conn = sqlite3.connect(fixture_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM segment_traffic_5min").fetchone()[0] == 72
    finally:
        conn.close()


def test_utc_until_same_as_kst(fixture_conn: sqlite3.Connection) -> None:
    from datetime import timezone

    n = run(UNTIL.astimezone(timezone.utc), conn=fixture_conn, lookback_minutes=LOOKBACK)
    assert n == 72
    r = fixture_conn.execute("SELECT processed_at FROM segment_traffic_5min LIMIT 1").fetchone()
    assert r[0] == to_iso(UNTIL)
    assert timedelta(0) == parse_iso(r[0]) - UNTIL


# --- Slice 1 규칙 (D-DAT-02b): 갱신 정지, 70% 기준, 측도, 짧은 결측 보정 ---


def _insert_obs_many(
    conn: sqlite3.Connection, rows: list[tuple[str, str, datetime, float]]
) -> None:
    """(source, link_id, source_timestamp, speed) 행을 collected_at = ts+40초로 넣는다."""
    conn.executemany(
        "INSERT INTO traffic_observation (source, link_id, source_timestamp, collected_at, speed, quality_flag)"
        " VALUES (?, ?, ?, ?, ?, 'ok')",
        [(src, lid, to_iso(ts), to_iso(ts + timedelta(seconds=40)), speed) for src, lid, ts, speed in rows],
    )
    conn.commit()


def test_frozen_requires_new_timestamps(fixture_conn: sqlite3.Connection) -> None:
    # S0(본선 링크 1개): 원본 시각이 바뀌는 동안 같은 speed가 8회(06:30~07:05) 이어지면
    # 6번째(06:55)부터 그 링크를 뺀다.
    fixture_conn.execute("DELETE FROM traffic_observation WHERE link_id = 'SYN0000000'")
    _insert_obs_many(
        fixture_conn, [("synthetic", "SYN0000000", _t(6, 30) + timedelta(minutes=5 * i), 30.0) for i in range(8)]
    )
    # S1: 원본 시각이 같은 반복(다른 수집원이 같은 시각)은 갱신 정지가 아니다. 6행이지만 시각은 3개.
    fixture_conn.execute("DELETE FROM traffic_observation WHERE link_id = 'SYN0000001'")
    _insert_obs_many(
        fixture_conn,
        [(src, "SYN0000001", ts, 40.0)
         for ts in (_t(6, 30), _t(6, 35), _t(6, 40)) for src in ("synthetic", "synthetic_b")],
    )
    run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)

    fifth = _row(fixture_conn, "S0", _t(6, 50))  # 5회 연속은 아직 정상
    assert fifth["quality_flag"] == "ok" and fifth["n_links_observed"] == 1
    sixth = _row(fixture_conn, "S0", _t(6, 55))
    assert sixth["n_links_observed"] == 0  # 6번째 관측은 갱신 정지로 집계에서 뺀다
    assert sixth["quality_flag"] == "imputed"  # 직전 실제 값(30.0)으로 짧은 결측 보정만 된다
    assert sixth["speed"] == pytest.approx(30.0)
    assert sixth["is_imputed"] == 1
    third_after = _row(fixture_conn, "S0", _t(7, 5))  # 7·8번째 관측도 빠져 3번째 연속 결측
    assert third_after["quality_flag"] == "missing" and third_after["speed"] is None

    # S1은 시각 3개가 반복된 6행뿐이므로 갱신 정지가 아니다. 시각을 행 수로 세면 여기서 오판한다.
    s1 = _row(fixture_conn, "S1", _t(6, 40))
    assert s1["quality_flag"] == "ok"
    assert (s1["n_links_expected"], s1["n_links_observed"]) == (2, 2)


def test_coverage_below_70_missing(fixture_conn: sqlite3.Connection) -> None:
    # S1 06:30에서 SYN0000002 관측을 빼면 관측 길이 500/1200 = 41.7% < 70% → missing.
    # 06:30은 창의 첫 bin이라 보정 근거(직전 실제 bin)도 없다.
    fixture_conn.execute(
        "DELETE FROM traffic_observation WHERE link_id = 'SYN0000002' AND source_timestamp = ?",
        (to_iso(_t(6, 30)),),
    )
    fixture_conn.commit()
    run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)
    r = _row(fixture_conn, "S1", _t(6, 30))
    assert r["speed"] is None
    assert r["quality_flag"] == "missing"
    assert r["is_imputed"] == 0
    assert (r["n_links_expected"], r["n_links_observed"]) == (2, 1)
    assert r["available_at"] == to_iso(_t(6, 35))  # missing은 bin 끝 시각


def test_coverage_partial_ok(fixture_conn: sqlite3.Connection) -> None:
    # 본선 길이 합 550 중 500 관측(90.9%) → partial로 산출한다. Slice 0과 달리 70% 미만만 missing이다.
    fixture_conn.execute("UPDATE segment_link SET link_length_m = 50 WHERE link_id = 'SYN0000002'")
    fixture_conn.execute(
        "DELETE FROM traffic_observation WHERE link_id = 'SYN0000002' AND source_timestamp = ?",
        (to_iso(_t(6, 30)),),
    )
    fixture_conn.commit()
    run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)
    r = _row(fixture_conn, "S1", _t(6, 30))
    assert r["speed"] == pytest.approx(fixture_speed("SYN0000001", _t(6, 30)))
    assert r["quality_flag"] == "partial"
    assert r["is_imputed"] == 0
    assert (r["n_links_expected"], r["n_links_observed"]) == (2, 1)


def test_side_speed(fixture_conn: sqlite3.Connection) -> None:
    # 측도 링크 2개(300m씩)를 S1에 붙인다. 본선과 같은 규칙(조화평균·커버리지 기준)으로 speed_side를 낸다.
    fixture_conn.executemany(
        "INSERT INTO segment_link (segment_id, link_id, source, seq, link_length_m, is_mainline,"
        " nodelink_ver, valid_from)"
        " VALUES ('S1', ?, 'synthetic', ?, 300.0, 0, 'synthetic', '2026-01-01T00:00:00+09:00')",
        [("SYN0000009", 3), ("SYN0000010", 4)],
    )
    fixture_conn.commit()
    _add_obs(fixture_conn, "SYN0000009", _t(6, 30), _t(6, 30, 40), 5.0)
    # 측도 관측을 본선보다 늦게 수집: speed_side의 근거라 available_at이 이 시각이어야 한다(I-1)
    _add_obs(fixture_conn, "SYN0000010", _t(6, 30), _t(6, 31, 30), 15.0)
    # 06:35에는 측도 하나만 관측(1/2 = 50% < 70%) → speed_side는 NULL
    _add_obs(fixture_conn, "SYN0000009", _t(6, 35), _t(6, 35, 40), 10.0)
    run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)

    r = _row(fixture_conn, "S1", _t(6, 30))
    v1, v2 = fixture_speed("SYN0000001", _t(6, 30)), fixture_speed("SYN0000002", _t(6, 30))
    assert r["speed"] == pytest.approx(_harmonic([500, 700], [v1, v2]))  # 본선 값 불변
    assert r["quality_flag"] == "ok"
    assert r["speed_side"] == pytest.approx(600 / (300 / 5 + 300 / 15))
    assert r["available_at"] == to_iso(_t(6, 31, 30))  # 본선(06:30:40)보다 늦은 측도 관측 시각

    r2 = _row(fixture_conn, "S1", _t(6, 35))
    assert r2["speed_side"] is None  # 측도 커버리지 미달
    assert r2["quality_flag"] == "ok"  # 측도는 구간 quality_flag에 영향을 주지 않는다
    assert r2["available_at"] == to_iso(_t(6, 35, 40))  # speed_side가 NULL이면 본선 관측만 근거


def test_imputed_flag(fixture_conn: sqlite3.Connection) -> None:
    # S0: 07:00~07:15 4 bin 연속 결측. 연속 결측 길이는 현재 bin까지로 판정하므로(브리프 결측 규칙 메모)
    # 1·2번째는 채워지고 3번째에서 처음 missing이 된다. 이미 채운 1·2번째는 뒤에 되돌리지 않는다.
    fixture_conn.execute(
        "DELETE FROM traffic_observation WHERE link_id = 'SYN0000000'"
        " AND source_timestamp >= ? AND source_timestamp < ?",
        (to_iso(_t(7, 0)), to_iso(_t(7, 20))),
    )
    fixture_conn.commit()
    run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)

    for b in (_t(7, 0), _t(7, 5)):
        r = _row(fixture_conn, "S0", b)
        assert r["quality_flag"] == "imputed"
        assert r["is_imputed"] == 1
        assert r["speed"] == pytest.approx(fixture_speed("SYN0000000", _t(6, 55)))
        assert r["n_links_observed"] == 0
        assert r["available_at"] == to_iso(parse_iso(r["bin_time"]) + timedelta(minutes=5))  # bin 끝
    for b in (_t(7, 10), _t(7, 15)):
        r = _row(fixture_conn, "S0", b)
        assert r["quality_flag"] == "missing"
        assert r["is_imputed"] == 0 and r["speed"] is None


def test_ffill_uses_past_only(fixture_conn: sqlite3.Connection) -> None:
    # 결측 뒤 bin(07:05)의 관측이 먼저 들어와 있어도 보정값은 결측 앞(06:55) 값이다.
    fixture_conn.execute(
        "DELETE FROM traffic_observation WHERE link_id = 'SYN0000000' AND source_timestamp IN (?, ?)",
        (to_iso(_t(7, 0)), to_iso(_t(7, 5))),
    )
    _add_obs(fixture_conn, "SYN0000000", _t(7, 5), _t(7, 5, 40), 20.0)
    run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)
    r = _row(fixture_conn, "S0", _t(7, 0))
    assert r["quality_flag"] == "imputed"
    assert r["speed"] == pytest.approx(fixture_speed("SYN0000000", _t(6, 55)))
    assert r["speed"] != pytest.approx(20.0)
    before = dict(r)
    run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)  # 같은 until로 다시 집계해도 같다
    assert dict(_row(fixture_conn, "S0", _t(7, 0))) == before


def test_no_chain_imputation(fixture_conn: sqlite3.Connection) -> None:
    # 5 bin 연속 결측: 앞 2개만 imputed, 이후는 missing. imputed bin을 근거로 이어서 채우지 않는다.
    fixture_conn.execute(
        "DELETE FROM traffic_observation WHERE link_id = 'SYN0000000'"
        " AND source_timestamp >= ? AND source_timestamp < ?",
        (to_iso(_t(7, 0)), to_iso(_t(7, 25))),
    )
    fixture_conn.commit()
    run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)
    flags = {b: _row(fixture_conn, "S0", b)["quality_flag"]
             for b in (_t(7, 0), _t(7, 5), _t(7, 10), _t(7, 15), _t(7, 20))}
    assert [flags[_t(7, 0)], flags[_t(7, 5)]] == ["imputed", "imputed"]
    assert [flags[_t(7, 10)], flags[_t(7, 15)], flags[_t(7, 20)]] == ["missing", "missing", "missing"]


def test_ffill_uses_db_history(fixture_conn: sqlite3.Connection) -> None:
    # 이번 실행 창(07:00 한 bin)의 직전 bin은 이번 실행 결과가 아니라 DB에 이미 있는 행(이전 실행 결과)이다.
    fixture_conn.execute(
        "DELETE FROM traffic_observation WHERE link_id = 'SYN0000000' AND source_timestamp = ?",
        (to_iso(_t(7, 0)),),
    )
    fixture_conn.commit()
    run(_t(7, 0, 30), conn=fixture_conn, lookback_minutes=60)  # 06:00~06:55 bin을 기록
    prev = _row(fixture_conn, "S0", _t(6, 55))
    assert prev["quality_flag"] == "ok"
    run(_t(7, 5, 30), conn=fixture_conn, lookback_minutes=5)  # 이번 창은 07:00뿐
    r = _row(fixture_conn, "S0", _t(7, 0))
    assert r["quality_flag"] == "imputed"
    assert r["is_imputed"] == 1
    assert r["speed"] == pytest.approx(prev["speed"])


def test_imputed_kept_after_source_lost(fixture_conn: sqlite3.Connection) -> None:
    # 브리프 결측 규칙 메모: 이미 기록한 imputed bin은 뒤에 되돌리지 않는다(되돌리면 같은 시각 예측의
    # 입력이 사후에 바뀌어 재현이 깨진다). 근거가 된 직전 bin이 사라진 뒤 다시 집계해도 값을 유지한다.
    fixture_conn.execute(
        "DELETE FROM traffic_observation WHERE link_id = 'SYN0000000' AND source_timestamp = ?",
        (to_iso(_t(7, 0)),),
    )
    fixture_conn.commit()
    run(_t(7, 5, 30), conn=fixture_conn, lookback_minutes=10)  # 06:55, 07:00 bin
    first = _row(fixture_conn, "S0", _t(7, 0))
    assert first["quality_flag"] == "imputed"
    # 근거 bin(06:55)을 관측과 함께 지운다: 다시 계산하면 missing이 되는 상황을 흉내 낸다.
    fixture_conn.execute("DELETE FROM traffic_observation WHERE link_id = 'SYN0000000'")
    fixture_conn.execute(
        "DELETE FROM segment_traffic_5min WHERE segment_id = 'S0' AND bin_time < ?", (to_iso(_t(7, 0)),)
    )
    fixture_conn.commit()
    run(_t(7, 5, 30), conn=fixture_conn, lookback_minutes=10)
    r = _row(fixture_conn, "S0", _t(7, 0))
    assert r["quality_flag"] == "imputed"
    assert r["is_imputed"] == 1
    assert r["speed"] == pytest.approx(first["speed"])
