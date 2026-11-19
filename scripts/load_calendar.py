"""달력(`calendar_info`) 적재 (SPEC 5.8, R-05).

- 공휴일(`is_holiday`, `holiday_name`): `holidays.KR(years=...)`(0.109, R-05 B8)에
  `config.settings.temp_holidays`(수동 보정 목록)를 덧붙인다. 패키지는 임시공휴일을 사후에만
  반영하므로(R-05 B6) 새 지정분은 설정값으로 넣는다.
- `is_industrial_vacation`·`is_school_vacation`: 설정의 연도별 범위 안 1, 같은 연도에 범위가
  하나도 없으면 NULL(모름), 있으면 범위 밖 0. 모르는 값을 0으로 확정하지 않는다(불변식 2).
- `is_holiday_adjacent`: 공휴일이 아닌 평일 중, 바로 앞 또는 뒤 평일 사이(주말을 포함한 비근무
  구간)에 공휴일이 낀 날 1, 그 밖 0. 연도 경계를 넘는 비근무 구간(예: 12/31 다음 날인 1/1 신정)도
  판정에 쓰므로 앞·뒤 연도의 공휴일까지 조회한다(I-1).

실행(저장소 루트): `python -m scripts.init_db`가 올해와 내년을 적재한다.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import holidays

from common.logsetup import get_logger
from config.settings import get_settings

log = get_logger("scripts.load_calendar")

# temp_holidays 설정은 날짜만 두므로(근거 확인 전) 이름은 임시공휴일로 저장한다.
# TODO(R-05): 설정에 이름·근거 URL을 함께 두기로 하면 여기와 settings 주석을 함께 갱신한다.
TEMP_HOLIDAY_NAME = "임시공휴일"

# 연휴 인접 판정을 위해 연도 경계 너머까지 보는 여유 일수. 한국 공휴일 클러스터(설·추석 연휴+주말)는
# 이보다 짧다(R-05). 이보다 긴 비근무 구간이 설정되면 경계 너머는 볼 수 없어 인접 0이 된다(보수적).
_PAD = timedelta(days=16)

_UPSERT = """
INSERT INTO calendar_info
    (date, is_holiday, holiday_name, is_school_vacation, is_industrial_vacation, is_holiday_adjacent)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT (date) DO UPDATE SET
    is_holiday = excluded.is_holiday,
    holiday_name = excluded.holiday_name,
    is_school_vacation = excluded.is_school_vacation,
    is_industrial_vacation = excluded.is_industrial_vacation,
    is_holiday_adjacent = excluded.is_holiday_adjacent
"""


def _dates_of_year(year: int) -> list[date]:
    """그 연도의 모든 날짜(1월 1일 ~ 12월 31일)."""
    out, d = [], date(year, 1, 1)
    while d.year == year:
        out.append(d)
        d += timedelta(days=1)
    return out


def _ranges_in_year(year: int, ranges: tuple[tuple[str, str], ...]) -> list[tuple[date, date]]:
    """그 연도와 겹치는 범위만 잘라 돌려준다. 연도에 범위가 없으면 빈 목록."""
    first, last = date(year, 1, 1), date(year, 12, 31)
    out: list[tuple[date, date]] = []
    for s, e in ranges:
        sd, ed = date.fromisoformat(s), date.fromisoformat(e)
        if sd <= last and ed >= first:
            out.append((max(sd, first), min(ed, last)))
    return out


def _in_ranges(d: date, ranges: list[tuple[date, date]]) -> bool:
    return any(s <= d <= e for s, e in ranges)


def _holiday_names(years: list[int], temp: tuple[str, ...]) -> dict[date, str]:
    """날짜 → 공휴일 이름. 패키지 결과에 임시공휴일 설정을 덧붙인다(이미 있는 날은 놔둔다)."""
    kr = holidays.KR(years=sorted(set(years)), language="ko")
    names: dict[date, str] = {d: str(name) for d, name in kr.items()}
    for s in temp:
        d = date.fromisoformat(s)
        if d not in names:
            names[d] = TEMP_HOLIDAY_NAME
    return names


def _adjacent_flags(dates: list[date], is_holiday: list[bool]) -> list[int]:
    """연휴 인접 평일 표시. 주말+공휴일로 이루어진 비근무 구간에 공휴일이 하나라도 들어 있으면
    그 구간의 바로 앞·뒤 평일을 1로 표시한다. 공휴일 없는 주말만 있는 주는 0이다."""
    n = len(dates)
    non_work = [is_holiday[i] or dates[i].weekday() >= 5 for i in range(n)]
    out = [0] * n
    i = 0
    while i < n:
        if not non_work[i]:
            i += 1
            continue
        j = i
        while j < n and non_work[j]:
            j += 1
        if any(is_holiday[k] for k in range(i, j)):
            if i > 0:
                out[i - 1] = 1
            if j < n:
                out[j] = 1
        i = j
    return out


def _adjacent_of_year(dates: list[date], names: dict[date, str]) -> list[int]:
    """연도 경계 너머의 공휴일까지 본 연휴 인접 표시(I-1).

    `dates` 양쪽에 `_PAD`만큼 여유를 두고 판정한 뒤, 적재 대상 연도 부분만 잘라 돌려준다.
    여유 구간의 공휴일은 `names`(앞·뒤 연도를 포함한 패키지 결과+임시공휴일)에서 본다.
    """
    start, end = dates[0] - _PAD, dates[-1] + _PAD
    ext = [start + timedelta(days=k) for k in range((end - start).days + 1)]
    flags = _adjacent_flags(ext, [d in names for d in ext])
    return flags[_PAD.days : _PAD.days + len(dates)]


def load(conn: sqlite3.Connection, years: list[int]) -> int:
    """연도별 모든 날짜를 `calendar_info`에 UPSERT하고 적재한 행 수를 돌려준다 (C-06 v2).

    - `is_holiday`·`holiday_name`: `holidays.KR` + `settings.temp_holidays`
    - `is_industrial_vacation`·`is_school_vacation`: 설정 범위 안 1, 그 연도에 범위가 하나도
      없으면 NULL(모름), 있으면 범위 밖 0
    - `is_holiday_adjacent`: 공휴일이 아닌 평일 중 바로 앞·뒤 평일 사이에 공휴일(주말 연결 포함)이
      낀 날 1, 그 밖 0

    같은 입력으로 다시 실행해도 결과가 같다. 함수 안에서 commit한다.
    """
    if not years:
        return 0
    settings = get_settings()
    year_list = sorted(set(years))
    # 연휴 인접 판정이 연도 경계를 넘으므로(I-1) 앞·뒤 연도 공휴일도 패키지에서 계산한다.
    boundary_years = sorted({y for y in year_list for y in (y - 1, y, y + 1)})
    names = _holiday_names(boundary_years, settings.temp_holidays)
    rows: list[tuple[str, int, str | None, int | None, int | None, int]] = []
    for year in year_list:
        dates = _dates_of_year(year)
        hol = [d in names for d in dates]
        adjacent = _adjacent_of_year(dates, names)
        industrial = _ranges_in_year(year, settings.industrial_vacations)
        school = _ranges_in_year(year, settings.school_vacations)
        for i, d in enumerate(dates):
            rows.append(
                (
                    d.isoformat(),
                    1 if hol[i] else 0,
                    names.get(d),
                    _vacation_flag(d, school),
                    _vacation_flag(d, industrial),
                    adjacent[i],
                )
            )
    try:
        conn.executemany(_UPSERT, rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    log.info("달력 %d행 적재 (연도 %s)", len(rows), year_list)
    return len(rows)


def _vacation_flag(d: date, ranges: list[tuple[date, date]]) -> int | None:
    """그 연도에 범위가 있으면 안·밖(1/0), 없으면 NULL(모름)."""
    if not ranges:
        return None
    return 1 if _in_ranges(d, ranges) else 0
