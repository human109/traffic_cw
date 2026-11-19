"""preprocessing.run 5분 구간 집계 v0 테스트 (D-DAT-02a). 입력은 합성 픽스처다(synthetic)."""

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
    r = _row(fixture_conn, "S1", _t(7, 10))
    assert r["speed"] == pytest.approx(fixture_speed("SYN0000001", _t(7, 10)))
    assert r["speed"] != 0
    assert r["quality_flag"] == "partial"
    assert (r["n_links_expected"], r["n_links_observed"]) == (2, 1)


def test_out_of_range_excluded(fixture_conn: sqlite3.Connection) -> None:
    run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)
    r = _row(fixture_conn, "S3", _t(7, 15))  # SYN0000004 out_of_range(200) → 길이 NULL인 SYN0000005만 남음
    assert r["speed"] == pytest.approx(fixture_speed("SYN0000005", _t(7, 15)))
    assert r["quality_flag"] == "unweighted"
    assert r["n_links_observed"] == 1


def test_missing_not_zero(fixture_conn: sqlite3.Connection) -> None:
    run(UNTIL, conn=fixture_conn, lookback_minutes=LOOKBACK)
    r = _row(fixture_conn, "S2", _t(7, 20))
    assert r["speed"] is None
    assert r["quality_flag"] == "missing"
    assert (r["n_links_expected"], r["n_links_observed"]) == (1, 0)
    assert r["available_at"] == to_iso(_t(7, 25))  # bin 끝 시각


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
    assert r["speed_side"] is None


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
    assert gap["speed"] is None and gap["quality_flag"] == "missing" and gap["n_links_observed"] == 0

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
