"""scripts.collection_rate 수집 성공률 테스트 (D-DAT-05, BOARD 최종 리뷰 I3).

기본 설정 `rate_window=("06:00", "10:00")` 기준으로 기대 칸 수를 계산한다(시작 포함·끝 제외,
48 bin). 운영 DB(`data/traffic.db`)는 절대 쓰지 않고 tmp DB만 쓴다.

기준 날짜: 2026-11-16(월) ~ 11-22(일). 11-17을 임시 공휴일로 넣는다.
"""

from __future__ import annotations

import io
import sqlite3
import sys
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from common.timeutil import KST, now_kst, to_iso
from config.segments import SEGMENTS
from config.settings import get_settings
from database.db import connect, init_db
from scripts.collection_rate import (
    DayRate,
    _bin_count,
    _parse_hhmm,
    main,
    max_target_streak,
    rate,
)
from scripts.load_segments import load
from tests.fixtures.synthetic_db import ROAD_A, ROAD_B, build_fixture_db

D_MON, D_TUE, D_WED = date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 18)
D_SAT, D_SUN = date(2026, 11, 21), date(2026, 11, 22)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(tmp_path / "t.db", create=True)
    init_db(c)
    yield c
    c.close()


def _add_segment(
    conn: sqlite3.Connection, segment_id: str, *, is_target: int = 1, is_active: int = 1
) -> None:
    conn.execute(
        "INSERT INTO road_segment (segment_id, road_name, start_node, end_node, direction, seq,"
        " is_target, is_active) VALUES (?, '합성도로', '합성A', '합성B', '합성방향', 0, ?, ?)",
        (segment_id, is_target, is_active),
    )


def _add_calendar(conn: sqlite3.Connection, day: date, *, is_holiday: int = 0) -> None:
    conn.execute(
        "INSERT INTO calendar_info (date, is_holiday) VALUES (?, ?)", (day.isoformat(), is_holiday)
    )


def _window_bins(day: date) -> list[str]:
    """그 날 rate_window 안의 5분 bin_time ISO 문자열 목록(시작 포함·끝 제외)."""
    start = datetime.combine(day, _parse_hhmm(get_settings().rate_window[0]), tzinfo=KST)
    end = datetime.combine(day, _parse_hhmm(get_settings().rate_window[1]), tzinfo=KST)
    out: list[str] = []
    ts = start
    while ts < end:
        out.append(to_iso(ts))
        ts += timedelta(minutes=5)
    return out


def _add_5min(
    conn: sqlite3.Connection,
    segment_id: str,
    bin_time: str,
    *,
    speed: float | None = 50.0,
    quality_flag: str = "ok",
) -> None:
    conn.execute(
        "INSERT INTO segment_traffic_5min (segment_id, bin_time, available_at, speed,"
        " n_links_expected, n_links_observed, is_imputed, quality_flag, processed_at)"
        " VALUES (?, ?, ?, ?, 1, 1, ?, ?, ?)",
        (
            segment_id,
            bin_time,
            bin_time,
            speed,
            1 if quality_flag == "imputed" else 0,
            quality_flag,
            bin_time,
        ),
    )


def _fill_day(
    conn: sqlite3.Connection, day: date, segment_id: str, *, quality_flag: str = "ok"
) -> None:
    for b in _window_bins(day):
        _add_5min(conn, segment_id, b, quality_flag=quality_flag)


def test_service_day_weekend_holiday(conn: sqlite3.Connection) -> None:
    _add_segment(conn, "T1")
    _add_calendar(conn, D_MON)
    _add_calendar(conn, D_TUE, is_holiday=1)  # 화요일 임시 공휴일 가정
    _add_calendar(conn, D_SAT)
    _add_calendar(conn, D_SUN)
    for d in (D_MON, D_TUE, D_SAT):  # 데이터가 있어도 service day가 아니면 rate는 None
        _fill_day(conn, d, "T1")

    out = rate(conn, D_MON, D_SUN)
    assert [r.date for r in out] == [D_MON + timedelta(days=i) for i in range(7)]

    mon = out[0]
    assert (mon.is_service_day, mon.expected, mon.observed, mon.rate) == (True, 48, 48, 1.0)
    # 공휴일: service day 아님, rate None. expected·observed는 참고용으로 센다.
    tue = out[1]
    assert (tue.is_service_day, tue.expected, tue.observed, tue.rate) == (False, 48, 48, None)
    # 달력 행이 없는 평일: 주말만 제외하므로 service day. 행이 없는 칸은 미관측.
    wed = out[2]
    assert (wed.is_service_day, wed.expected, wed.observed, wed.rate) == (True, 48, 0, 0.0)
    # 주말: 달력 행이 있어도 service day 아님.
    for r in out[5:7]:
        assert r.is_service_day is False and r.rate is None


def test_imputed_and_missing_rows_excluded(conn: sqlite3.Connection) -> None:
    _add_segment(conn, "T1")
    _add_calendar(conn, D_MON)
    bins = _window_bins(D_MON)
    for i, b in enumerate(bins):
        if i == 0:
            _add_5min(conn, "T1", b, quality_flag="imputed")  # speed가 있어도 보정은 제외
        elif i == 1:
            _add_5min(conn, "T1", b, speed=None, quality_flag="missing")  # speed NULL은 제외
        elif i < 40:
            _add_5min(conn, "T1", b)  # 40칸 미만은 행이 없다 → 미관측
    (r,) = rate(conn, D_MON, D_MON)
    assert (r.expected, r.observed) == (48, 38)
    assert r.rate == pytest.approx(38 / 48)


def test_segment_count_reflected(conn: sqlite3.Connection) -> None:
    _add_segment(conn, "T1")
    _add_segment(conn, "T2")
    _add_segment(conn, "N1", is_target=0)  # 대상 아님 → expected에 안 들어감
    _add_segment(conn, "T3", is_active=0)  # 비활성 → expected에 안 들어감
    _add_calendar(conn, D_MON)
    for sid in ("T1", "T2", "N1", "T3"):
        _fill_day(conn, D_MON, sid)

    (r,) = rate(conn, D_MON, D_MON)
    assert r.expected == 96  # 48 bin × 대상 2구간
    assert r.observed == 96  # N1·T3의 96칸은 세지 않는다
    assert r.rate == 1.0


def test_no_target_segments_gives_rate_none(conn: sqlite3.Connection) -> None:
    _add_calendar(conn, D_MON)
    (r,) = rate(conn, D_MON, D_MON)
    assert r.is_service_day is True
    assert (r.expected, r.observed, r.rate) == (0, 0, None)  # 0으로 나누지 않는다


def test_rate_does_not_write(conn: sqlite3.Connection) -> None:
    _add_segment(conn, "T1")
    _add_calendar(conn, D_MON)
    _fill_day(conn, D_MON, "T1")
    rate(conn, D_MON, D_MON)
    # 읽기 전용 함수라 commit하지 않아도 데이터가 그대로다.
    n = conn.execute("SELECT COUNT(*) FROM segment_traffic_5min").fetchone()[0]
    assert n == 48


def test_bin_count_rejects_bad_window() -> None:
    assert _bin_count(("06:00", "10:00")) == 48
    with pytest.raises(ValueError):  # 끝이 시작보다 이른 창은 설정 오류다
        _bin_count(("10:00", "06:00"))
    with pytest.raises(ValueError):  # 같은 창도 마찬가지다
        _bin_count(("06:00", "06:00"))


def test_max_target_streak_skips_non_service_days() -> None:
    d0 = date(2026, 11, 16)  # 월
    days = [
        DayRate(d0, None, True, 48, 48, 1.0),
        DayRate(d0 + timedelta(days=1), None, True, 48, 47, 47 / 48),
        DayRate(d0 + timedelta(days=2), None, False, 48, 48, None),  # 공휴일: 연속에서 무시
        DayRate(d0 + timedelta(days=3), None, True, 48, 48, 1.0),
    ]
    assert max_target_streak(days, 0.95) == 3
    # 목표 미달 하루가 연속을 끊는다.
    days[1] = DayRate(d0 + timedelta(days=1), None, True, 48, 40, 40 / 48)
    assert max_target_streak(days, 0.95) == 1
    # 판정 불가(expected 0)도 연속을 끊는다.
    days[1] = DayRate(d0 + timedelta(days=1), None, True, 0, 0, None)
    assert max_target_streak(days, 0.95) == 1


# --- C-01 v1.4 / C-06 v2.3 도로별 성공률 (W-02) ---


def test_rate_by_road_counts_only_that_road(fixture_conn_two: sqlite3.Connection) -> None:
    """road_name을 주면 그 도로의 대상 구간만 분모·분자다(다른 도로는 새지 않는다)."""
    (a,) = rate(fixture_conn_two, D_MON, D_MON, road_name=ROAD_A)
    assert (a.road_name, a.expected) == (ROAD_A, 48 * 3)  # S1·S2·S3
    (b,) = rate(fixture_conn_two, D_MON, D_MON, road_name=ROAD_B)
    assert (b.road_name, b.expected) == (ROAD_B, 48 * 2)  # W1·W2 (W0은 참고 구간)
    (all_roads,) = rate(fixture_conn_two, D_MON, D_MON)
    assert (all_roads.road_name, all_roads.expected) == (None, 48 * 5)  # 전체 대상 구간 합산


def test_rate_road_name_unknown_gives_zero_expectation(fixture_conn_two: sqlite3.Connection) -> None:
    # 없는 도로 이름이면 예외 대신 기대 0 · rate None(0으로 나누지 않는다).
    (r,) = rate(fixture_conn_two, D_MON, D_MON, road_name="없는도로")
    assert (r.expected, r.observed, r.rate) == (0, 0, None)


def test_rate_none_excludes_non_target_road(tmp_path: Path) -> None:
    """`second_road_target=False`(target_corridors에 없음)면 W 구간이 합산 분모에 새지 않는다."""
    db = build_fixture_db(tmp_path / "f.db", second_road=True, second_road_target=False)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        (r,) = rate(conn, D_MON, D_MON)
        assert r.expected == 48 * 3  # 합성도로 S1~S3만. W는 is_target=0
        (w,) = rate(conn, D_MON, D_MON, road_name=ROAD_B)
        assert (w.expected, w.rate) == (0, None)
    finally:
        conn.close()


def _seed_one_target_segment(conn: sqlite3.Connection) -> None:
    _add_segment(conn, "T1")
    conn.commit()


def test_main_reads_readonly_and_prints(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    c = connect(tmp_path / "t.db", create=True)
    init_db(c)
    _seed_one_target_segment(c)
    c.close()
    seen: dict[str, object] = {}

    def fake_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        seen.update(kwargs)
        return connect(tmp_path / "t.db", readonly=True)

    monkeypatch.setattr("scripts.collection_rate.connect", fake_connect)
    assert main(["--days", "3"]) == 0
    out = capsys.readouterr().out
    assert seen == {"readonly": True}  # CLI는 readonly로 연결한다
    assert "[합성도로]" in out  # 도로별 표 (settings.corridors에 없는 도로도 표에 나온다)
    assert "날짜" in out and "expected" in out
    assert "연속 service day 3일 이상" in out


def test_main_prints_table_per_road_in_corridor_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = build_fixture_db(tmp_path / "two.db", second_road=True)  # 두 도로 모두 대상
    monkeypatch.setattr(
        "scripts.collection_rate.connect", lambda *a, **k: connect(db, readonly=True)
    )
    assert main(["--days", "2"]) == 0
    out = capsys.readouterr().out
    # settings.corridors(창원대로, 원이대로)에 없는 합성 도로는 이름 순으로 뒤에 붙는다.
    assert out.index("[합성도로]") < out.index("[합성도로B]")
    assert out.count("연속 service day") == 2  # 연속 판정 줄도 도로별


def test_main_shows_only_roads_with_target_segments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # 실제 시드: 원이대로는 target_corridors에 없어 is_target=0 → 대상 구간이 없으니 표에 안 나온다.
    c = connect(tmp_path / "seed.db", create=True)
    init_db(c)
    load(c, SEGMENTS, Path(__file__).resolve().parents[2] / "config" / "segment_links.csv")
    c.close()
    monkeypatch.setattr(
        "scripts.collection_rate.connect", lambda *a, **k: connect(tmp_path / "seed.db", readonly=True)
    )
    assert main(["--days", "2"]) == 0
    out = capsys.readouterr().out
    assert "[창원대로]" in out
    assert "원이대로" not in out
    assert out.count("연속 service day") == 1  # 대상 구간이 있는 도로만


def test_main_without_target_segments_prints_no_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    c = connect(tmp_path / "t.db", create=True)
    init_db(c)
    c.close()
    monkeypatch.setattr(
        "scripts.collection_rate.connect", lambda *a, **k: connect(tmp_path / "t.db", readonly=True)
    )
    assert main(["--days", "2"]) == 0
    out = capsys.readouterr().out
    assert "대상 구간이 없어" in out  # 빈 표를 억지로 그리지 않는다
    assert "연속 service day" not in out


def test_main_prints_to_strict_cp949_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PowerShell 리디렉션(`| Out-File`)·파이프처럼 표준출력이 cp949(엄격)로 다시 열려도
    # UnicodeEncodeError로 죽지 않아야 한다 (D-DAT-06). 모든 날을 공휴일로 두어 rate는 None이다.
    c = connect(tmp_path / "t.db", create=True)
    init_db(c)
    _seed_one_target_segment(c)
    today = now_kst().date()
    for i in range(4):
        c.execute(
            "INSERT INTO calendar_info (date, is_holiday) VALUES (?, 1)",
            ((today - timedelta(days=i)).isoformat(),),
        )
    c.commit()
    c.close()
    monkeypatch.setattr(
        "scripts.collection_rate.connect",
        lambda *args, **kwargs: connect(tmp_path / "t.db", readonly=True),
    )
    buf = io.BytesIO()
    stream = io.TextIOWrapper(buf, encoding="cp949", errors="strict", newline="\n")
    monkeypatch.setattr(sys, "stdout", stream)

    assert main(["--days", "4"]) == 0
    stream.flush()
    text = buf.getvalue().decode("cp949")
    assert "연속 service day" in text
    assert "-" in text  # rate 없음 표시는 CP949에 있는 ASCII '-'다
    assert "—" not in text  # CP949에 없는 문자를 표에 쓰지 않는다
