"""날짜별 수집 성공률 조회 (BOARD 최종 리뷰 I3, C-06 v2.3).

정의(BOARD I3): 평일·비공휴일(service day)의 `rate_window`(bin_time 기준, 시작 포함·끝 제외)
안 5분 bin 수 × 예측 대상(`road_segment.is_target=1`·`is_active=1`) 구간 수가 expected이고,
그 칸 중 `segment_traffic_5min.speed IS NOT NULL`이고 `quality_flag != 'imputed'`인 칸이
observed다. 행이 없는 칸은 미관측이다. 회차 상태(`partial`·`no_update`)가 아니라 실제로 쓸
수 있는 데이터 기준이므로, 보정(`imputed`)한 값은 아직 실제 관측이 아니라서 제외한다.

실행(저장소 루트): `python -m scripts.collection_rate [--days 7]` — readonly 연결로 읽는다.
출력은 cp949 콘솔·리디렉션에서도 죽지 않도록 ASCII만 쓴다(rate 없음은 '-', D-DAT-06).
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from common.logsetup import get_logger
from common.timeutil import KST, now_kst, to_iso
from config.settings import get_settings
from database.db import connect
from scripts._console import make_stdout_lenient

log = get_logger("scripts.collection_rate")

_OBSERVED_SQL = """
SELECT COUNT(*)
FROM segment_traffic_5min AS t
JOIN road_segment AS s ON s.segment_id = t.segment_id
WHERE s.is_target = 1
  AND s.is_active = 1
  {road_filter}
  AND t.bin_time >= ?
  AND t.bin_time < ?
  AND t.speed IS NOT NULL
  AND t.quality_flag <> 'imputed'
"""

_TARGET_SEGMENTS = "is_target = 1 AND is_active = 1"


@dataclass(frozen=True)
class DayRate:
    """하루의 수집 성공률 (C-06 v2.3).

    `road_name`은 이 행이 센 도로다. `rate(..., road_name=None)`이면 모든 대상 구간을 합산하고
    None이다. service day(평일·비공휴일)가 아니면 `rate`는 None이다. service day라도 expected가
    0이면(대상 구간이 없거나 창이 비면) 나눌 수 없어 None이다. service day가 아닌 날의
    expected·observed는 참고용으로 그대로 센다(0으로 감추지 않는다).
    """

    date: date
    road_name: str | None
    is_service_day: bool
    expected: int
    observed: int
    rate: float | None


def _parse_hhmm(s: str) -> time:
    """"HH:MM"을 `time`으로 읽는다."""
    h, m = (int(x) for x in s.split(":"))
    return time(h, m)


def _bin_count(window: tuple[str, str]) -> int:
    """`rate_window`("HH:MM", "HH:MM") 안에 들어가는 5분 bin 수. 시작 포함·끝 제외.

    경계가 5분 단위가 아니면 잘린 만큼만 센다(설정은 5분 단위로 쓴다). 끝이 시작보다 같거나
    이르면 설정 오류이므로 ValueError를 낸다(잘못된 설정을 빈 결과로 숨기지 않는다).
    """
    t1, t2 = _parse_hhmm(window[0]), _parse_hhmm(window[1])
    minutes = (t2.hour * 60 + t2.minute) - (t1.hour * 60 + t1.minute)
    if minutes <= 0:
        raise ValueError(f"rate_window 끝이 시작보다 같거나 이르다: {window}")
    return minutes // 5


def _window_bounds(day: date, window: tuple[str, str]) -> tuple[str, str]:
    """그 날 rate_window의 [시작, 끝) bin_time ISO 문자열(비교는 문자열로 가능하다)."""
    t1, t2 = _parse_hhmm(window[0]), _parse_hhmm(window[1])
    lo = to_iso(datetime.combine(day, t1, tzinfo=KST))
    hi = to_iso(datetime.combine(day, t2, tzinfo=KST))
    return lo, hi


def _is_service_day(conn: sqlite3.Connection, day: date) -> bool:
    """평일이고 `calendar_info.is_holiday`가 1이 아니면 service day.

    달력 행이 없으면 주말만 제외한다(지정되지 않은 날을 공휴일로 단정하지 않는다).
    """
    if day.weekday() >= 5:  # 5=토, 6=일
        return False
    row = conn.execute(
        "SELECT is_holiday FROM calendar_info WHERE date = ?", (day.isoformat(),)
    ).fetchone()
    return row is None or row["is_holiday"] != 1


def _day_rate(
    conn: sqlite3.Connection,
    day: date,
    n_bins: int,
    n_segments: int,
    window: tuple[str, str],
    road_name: str | None,
) -> DayRate:
    """하루분을 계산한다. 관측 행은 bin_time 문자열 범위로만 센다."""
    service = _is_service_day(conn, day)
    expected = n_bins * n_segments
    lo, hi = _window_bounds(day, window)
    if road_name is None:
        sql, params = _OBSERVED_SQL.format(road_filter=""), (lo, hi)
    else:
        sql, params = _OBSERVED_SQL.format(road_filter="AND s.road_name = ?"), (road_name, lo, hi)
    observed = int(conn.execute(sql, params).fetchone()[0])
    rate: float | None = observed / expected if service and expected > 0 else None
    return DayRate(day, road_name, service, expected, observed, rate)


def _target_segment_count(conn: sqlite3.Connection, road_name: str | None) -> int:
    """예측 대상 구간 수. `road_name`이 None이면 모든 도로의 대상 구간을 센다."""
    if road_name is None:
        return int(
            conn.execute(f"SELECT COUNT(*) FROM road_segment WHERE {_TARGET_SEGMENTS}").fetchone()[0]
        )
    return int(
        conn.execute(
            f"SELECT COUNT(*) FROM road_segment WHERE {_TARGET_SEGMENTS} AND road_name = ?",
            (road_name,),
        ).fetchone()[0]
    )


def rate(
    conn: sqlite3.Connection, start_date: date, end_date: date, road_name: str | None = None
) -> list[DayRate]:
    """날짜별 수집 성공률을 계산한다 (C-06 v2.3).

    `start_date`부터 `end_date`까지(포함, KST 날짜) 하루씩 `DayRate`를 돌려준다. 기대 칸 수는
    `rate_window` 안 5분 bin 수 × `is_target=1`·`is_active=1` 구간 수이고, observed는 그 칸 중
    speed가 있고 `quality_flag != 'imputed'`인 칸 수다(행이 없으면 미관측).

    `road_name`을 주면 그 도로의 대상 구간만 센다(다른 도로는 분모·분자에 들어가지 않는다).
    None이면 모든 도로의 대상 구간을 합산하고 `DayRate.road_name`은 None이다. 예측 대상이 아닌
    도로는 `is_target=0`이므로 어느 쪽에도 새지 않는다. 읽기만 하고 commit 하지 않는다.
    """
    settings = get_settings()
    window = settings.rate_window
    n_bins = _bin_count(window)
    n_segments = _target_segment_count(conn, road_name)
    out: list[DayRate] = []
    day = start_date
    while day <= end_date:
        out.append(_day_rate(conn, day, n_bins, n_segments, window, road_name))
        day += timedelta(days=1)
    return out


def _target_roads(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """대상 구간이 있는 도로와 그 구간 수를 표시 순서로 돌려준다.

    순서는 `settings.corridors` 인덱스이고, 목록에 없는 도로는 뒤에 이름 순으로 붙인다(C-01 v1.4
    정렬 규칙). 대상 구간이 없는 도로는 표에 그리지 않는다.
    """
    counts = {
        row[0]: int(row[1])
        for row in conn.execute(
            f"SELECT road_name, COUNT(*) FROM road_segment WHERE {_TARGET_SEGMENTS} GROUP BY road_name"
        )
    }
    corridors = list(get_settings().corridors)
    ordered = [road for road in corridors if road in counts]
    ordered += sorted(road for road in counts if road not in corridors)
    return [(road, counts[road]) for road in ordered]


def max_target_streak(results: list[DayRate], target: float) -> int:
    """`rate >= target`인 service day의 최장 연속 일수.

    service day가 아닌 날은 연속 판정에서 무시한다(주말은 service day가 아니므로 금→월도
    연속 service day로 센다). rate를 판정할 수 없는 service day(expected 0)는 연속을 끊는다.
    """
    best = cur = 0
    for r in results:
        if not r.is_service_day:
            continue
        if r.rate is not None and r.rate >= target:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def main(argv: list[str] | None = None) -> int:
    """CLI: 최근 `--days`일(KST, 오늘 포함)의 날짜별 표와 연속 목표 충족 여부를 출력한다.

    표준출력이 cp949여도(`| Out-File` 등 리디렉션) 죽지 않게 인코딩 오류를 대체 문자로 넘기고,
    출력 문자열 자체도 CP949에 없는 문자를 쓰지 않는다(`-`, `>=`).
    """
    make_stdout_lenient()
    parser = argparse.ArgumentParser(description="날짜별 수집 성공률 조회 (readonly 연결)")
    parser.add_argument("--days", type=int, default=7, help="오늘(KST)부터 포함해 볼 일수 (기본 7)")
    args = parser.parse_args(argv)
    if args.days < 1:
        parser.error("--days는 1 이상이어야 한다")

    settings = get_settings()
    end = now_kst().date()
    start = end - timedelta(days=args.days - 1)
    conn = connect(readonly=True)
    try:
        roads = _target_roads(conn)
        results = {road: rate(conn, start, end, road_name=road) for road, _ in roads}
    finally:
        conn.close()

    print(
        f"기간 {start} ~ {end} / rate_window {settings.rate_window[0]}~{settings.rate_window[1]}"
        f"(끝 제외) / 대상 구간 is_target=1·is_active=1"
    )
    if not roads:
        print("대상 구간이 없어 표를 출력하지 않는다(is_target=1인 구간이 있는 DB인지 확인).")
        log.info("수집 성공률 조회: %s ~ %s (대상 구간 없음)", start, end)
        return 0
    for road, n_segments in roads:
        print(f"[{road}] 대상 구간 {n_segments}개")
        print("날짜        service  expected  observed  rate")
        rows = results[road]
        for r in rows:
            mark = "예" if r.is_service_day else "아니오"
            rate_txt = "-" if r.rate is None else f"{r.rate * 100:.1f}%"
            print(f"{r.date}  {mark:<5}  {r.expected:>8}  {r.observed:>8}  {rate_txt:>7}")
        streak = max_target_streak(rows, settings.rate_target)
        required = settings.rate_streak_days
        verdict = "충족" if streak >= required else "미충족"
        print(
            f"연속 service day {required}일 이상 >= rate_target"
            f"({settings.rate_target:.0%}): {verdict} (최대 {streak}일)"
        )
    now = now_kst()
    if now.date() == end and now.time() < _parse_hhmm(settings.rate_window[1]):
        print("(오늘은 rate_window가 끝나기 전이라 실제보다 낮게 나올 수 있다)")
    log.info("수집 성공률 조회: %s ~ %s (도로 %d개)", start, end, len(roads))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
