"""scripts.load_calendar 달력 적재 테스트 (D-DAT-04).

공휴일 값은 설치된 `holidays==0.109`(R-05 B8 표)와 `config/settings.py` 설정값에서 나온다.
테스트는 네트워크를 쓰지 않는다.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import holidays
import pytest

from common.timeutil import KST, to_iso

from config.settings import get_settings
from database.db import connect, init_db
from scripts.load_calendar import load


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(tmp_path / "t.db", create=True)
    init_db(c)
    yield c
    c.close()


def _row(conn: sqlite3.Connection, d: str) -> sqlite3.Row:
    return conn.execute("SELECT * FROM calendar_info WHERE date = ?", (d,)).fetchone()


def test_holidays_2026(conn: sqlite3.Connection) -> None:
    load(conn, [2026])
    # 추석 연휴 (R-05 1장 표)
    for d, name in [("2026-09-24", "추석 전날"), ("2026-09-25", "추석"), ("2026-09-26", "추석 다음날")]:
        r = _row(conn, d)
        assert r["is_holiday"] == 1
        assert r["holiday_name"] == name
    # 2026년부터 노동절·제헌절이 공휴일이다 (R-05 B4·C1)
    assert _row(conn, "2026-05-01")["holiday_name"] == "노동절"
    assert _row(conn, "2026-07-17")["is_holiday"] == 1
    # 지방선거일도 패키지에 들어 있다 (R-05 B5)
    assert _row(conn, "2026-06-03")["is_holiday"] == 1
    # 주말은 공휴일이 아니다 (0은 "아님"이 확인된 경우만, C-01)
    assert _row(conn, "2026-09-12")["is_holiday"] == 0 and _row(conn, "2026-09-12")["holiday_name"] is None


def test_one_row_per_date_of_year(conn: sqlite3.Connection) -> None:
    n = load(conn, [2026])
    assert n == 365  # 연도의 모든 날짜 1행
    lo, hi, cnt = conn.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM calendar_info").fetchone()
    assert (lo, hi, cnt) == ("2026-01-01", "2026-12-31", 365)


def test_industrial_vacation(conn: sqlite3.Connection) -> None:
    load(conn, [2026, 2027])
    # 설정 industrial_vacations(("2026-08-03","2026-08-07"), R-05 E5) 안은 1
    assert _row(conn, "2026-08-05")["is_industrial_vacation"] == 1
    # 같은 연도에 범위가 있으면 범위 밖은 0
    assert _row(conn, "2026-08-12")["is_industrial_vacation"] == 0
    # 그 연도에 범위가 하나도 없으면 NULL(모름) — 0이 아니다 (불변식 2)
    assert _row(conn, "2027-08-05")["is_industrial_vacation"] is None


def test_school_vacation_all_null(conn: sqlite3.Connection) -> None:
    # school_vacations가 비어 있으므로 전부 NULL(모름)이다
    load(conn, [2026, 2027])
    cnt = conn.execute("SELECT COUNT(*) FROM calendar_info WHERE is_school_vacation IS NOT NULL").fetchone()[0]
    assert cnt == 0


def test_holiday_adjacent_chuseok(conn: sqlite3.Connection) -> None:
    load(conn, [2026])
    # 추석 비근무 구간(9/24 목~9/27 일)의 바로 앞 평일 9/23(수)과 다음 평일 9/28(월)은 1
    assert _row(conn, "2026-09-23")["is_holiday_adjacent"] == 1
    assert _row(conn, "2026-09-28")["is_holiday_adjacent"] == 1
    # 공휴일·주말 자체와 구간 안의 날은 대상이 아니다
    assert _row(conn, "2026-09-24")["is_holiday_adjacent"] == 0
    assert _row(conn, "2026-09-26")["is_holiday_adjacent"] == 0


def test_holiday_adjacent_ordinary_week_is_zero(conn: sqlite3.Connection) -> None:
    load(conn, [2026])
    # 주말만 있는 주: 공휴일이 끼지 않으므로 0이다
    assert _row(conn, "2026-09-18")["is_holiday_adjacent"] == 0  # 금
    assert _row(conn, "2026-09-21")["is_holiday_adjacent"] == 0  # 월


def test_holiday_adjacent_single_weekday_holiday(conn: sqlite3.Connection) -> None:
    load(conn, [2026])
    # 6/3(수) 지방선거일 하나가 끼면 그 앞뒤 평일(6/2 화, 6/4 목)이 1이다
    assert _row(conn, "2026-06-02")["is_holiday_adjacent"] == 1
    assert _row(conn, "2026-06-04")["is_holiday_adjacent"] == 1
    # 6/5(금)도 1이다: 뒤의 주말에 현충일(6/6 토)이 연결되어 있기 때문이다
    assert _row(conn, "2026-06-05")["is_holiday_adjacent"] == 1
    # 공휴일과 무관한 평일은 0이다
    assert _row(conn, "2026-06-09")["is_holiday_adjacent"] == 0


def test_holiday_adjacent_across_year_boundary(conn: sqlite3.Connection) -> None:
    # 연휴 인접 판정은 연도 경계를 넘어야 한다(I-1). 적재 연도가 아니어도 앞·뒤 연도의
    # 공휴일을 패키지로 계산해 본다.
    load(conn, [2026])
    # 2026-12-31(목)은 바로 뒤 비근무 구간(2027-01-01 신정~01-03)에 공휴일이 끼므로 1
    assert _row(conn, "2026-12-31")["is_holiday_adjacent"] == 1
    # 2026-01-02(금)는 신정(1/1 목) 바로 뒤 평일이므로 1
    assert _row(conn, "2026-01-02")["is_holiday_adjacent"] == 1
    # 연도 경계와 무관한 평일은 그대로 0이다(1/3~1/4 주말 뒤지만 공휴일이 없다)
    assert _row(conn, "2026-01-05")["is_holiday_adjacent"] == 0


def test_holiday_adjacent_next_year_boundary(conn: sqlite3.Connection) -> None:
    load(conn, [2027])
    # 2027-12-31(금)은 2028-01-01(토, 신정)로 이어지는 비근무 구간의 앞 평일이므로 1
    assert _row(conn, "2027-12-31")["is_holiday_adjacent"] == 1


def test_substitute_holidays_marked(conn: sqlite3.Connection) -> None:
    # 대체공휴일 날짜를 추측하지 않고 패키지에서 찾아 확인한다(R-05 B3: "<명칭> 대체 휴일").
    kr = holidays.KR(years=2026, language="ko")
    subs = sorted(d for d, name in kr.items() if "대체" in str(name))
    assert subs, "holidays 0.109가 2026년 대체공휴일을 줘야 한다(R-05 B4)"
    load(conn, [2026])
    for d in subs:
        r = _row(conn, d.isoformat())
        assert r["is_holiday"] == 1
        assert r["holiday_name"] == str(kr.get(d))


def test_temp_holiday_added(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    # 패키지에 없는 임시공휴일은 설정값으로 보정한다(R-05 1장 3번)
    monkeypatch.setattr(
        "scripts.load_calendar.get_settings",
        lambda: dataclasses.replace(get_settings(), temp_holidays=("2026-12-31",)),
    )
    load(conn, [2026])
    r = _row(conn, "2026-12-31")
    assert r["is_holiday"] == 1
    assert r["holiday_name"] == "임시공휴일"


def test_load_twice_idempotent(conn: sqlite3.Connection) -> None:
    n1 = load(conn, [2026, 2027])
    n2 = load(conn, [2026, 2027])
    assert n1 == n2 == 730
    assert conn.execute("SELECT COUNT(*) FROM calendar_info").fetchone()[0] == 730
    # 값도 바뀌지 않는다
    r1 = _row(conn, "2026-09-25")
    load(conn, [2026, 2027])
    assert dict(_row(conn, "2026-09-25")) == dict(r1)


def test_upsert_overwrites_when_settings_change(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 재적재가 값을 덮어쓴다(예: 설정이 바뀌어 산단 휴가가 새로 생긴 경우)
    load(conn, [2027])
    assert _row(conn, "2027-08-05")["is_industrial_vacation"] is None
    monkeypatch.setattr(
        "scripts.load_calendar.get_settings",
        lambda: dataclasses.replace(get_settings(), industrial_vacations=(("2027-08-02", "2027-08-06"),)),
    )
    load(conn, [2027])
    assert _row(conn, "2027-08-05")["is_industrial_vacation"] == 1
    assert _row(conn, "2027-08-10")["is_industrial_vacation"] == 0  # 이제 범위가 있으므로 밖은 0
