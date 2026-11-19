"""5분 구간 집계 (SPEC 6.2~6.4, C-01 v1.2).

`traffic_observation`(링크 단위 관측)을 읽어 `segment_traffic_5min`(구간 x 5분 bin)에 쓴다.
판정 규칙은 DB를 모르는 순수 함수로 `preprocessing.rules`에 뒀다.

규칙(순서대로):
- 대상 bin: `[floor_5min(until) - lookback, floor_5min(until))`. 끝난 bin만 처리하므로 미완성 bin은
  쓰지 않는다. lookback이 5의 배수가 아니면 시작을 다음 5분 경계로 올린다(창이 lookback보다 넓어지지 않음).
- 링크: bin 시작 시각에 유효(`valid_from <= bin < valid_to 또는 NULL`)한 링크. 본선(`is_mainline=1`)과
  측도(0)를 따로 집계한다. 관측 대조는 `link_id`로만 한다(`segment_link.source`는 링크 ID 체계 출처라
  거르지 않는다, C-01 v1.1).
- 링크별 관측: 같은 bin, `collected_at <= until`, `quality_flag='ok'`, `speed > 0` 중
  `source_timestamp`가 가장 늦은 1건. 미래에 수집된 관측은 쓰지 않는다.
  (ok인데 speed<=0인 행은 경고 로그 후 제외)
- 갱신 정지: 링크별로 원본 시각(`source_timestamp`)이 서로 다른 관측을 시간순으로 볼 때 같은 speed가
  `frozen_repeat_count`회 이상 이어지면 그 6번째부터 집계에서 뺀다. 판정을 위해 창보다
  `frozen_repeat_count x 5분` 더 앞의 관측까지 읽는다. 원본 시각이 같은 반복은 1건으로 센다.
- 본선 속도: 관측 본선 길이 합 / 전체 본선 길이 합 >= `partial_min_coverage`일 때만 산출
  (전부면 `ok`, 아니면 `partial`), 미만이면 NULL(`missing`). 길이를 모르는 링크가 섞이면 단순 평균
  (`unweighted`). 결측을 0으로 바꾸지 않는다.
- 측도 속도(`speed_side`): 같은 규칙(조화평균, 커버리지 기준). 측도가 없거나 기준 미달이면 NULL.
  구간 `quality_flag`에는 영향 없음.
- 짧은 결측 보정: 본선 결과가 `missing`인 bin의 직전 연속 결측(그 bin 포함, `imputed`도 결측으로 센다)이
  `ffill_max_bins` 이하이고 그 앞 bin이 실제 값이면 그 값으로 채운다 → `quality_flag='imputed'`,
  `is_imputed=1`, `available_at`=bin 끝. 보정값을 다시 보정의 근거로 쓰지 않고, 이미 기록한 `imputed`
  bin은 뒤에 결측이 길어져도 되돌리지 않는다(같은 시각 예측 입력의 재현 유지). 직전 bin은 이번 실행
  결과와 DB에 이미 있는 행(이전 실행 결과) 모두에서 찾는다.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from common.logsetup import get_logger
from common.timeutil import floor_5min, parse_iso, require_aware, to_iso
from config.settings import get_settings
from preprocessing import rules

log = get_logger("preprocessing.aggregate")

BIN = timedelta(minutes=5)  # floor_5min과 같은 bin 크기


@dataclass(frozen=True)
class _Link:
    segment_id: str
    link_id: str
    length_m: float | None
    is_mainline: bool
    valid_from: datetime
    valid_to: datetime | None

    def valid_at(self, t: datetime) -> bool:
        return self.valid_from <= t and (self.valid_to is None or t < self.valid_to)


@dataclass(frozen=True)
class _Obs:
    row_id: int
    link_id: str
    source_timestamp: datetime
    collected_at: datetime
    speed: float


@dataclass(frozen=True)
class _Existing:
    """DB에 이미 기록된 bin 행(이전 실행 결과)."""

    speed: float | None
    quality_flag: str
    is_imputed: bool


def _bins(until: datetime, lookback_minutes: int) -> list[datetime]:
    """`[floor_5min(until) - lookback, floor_5min(until))`에 시작하는 bin.

    lookback이 5의 배수가 아니면 시작을 다음 5분 경계로 올려 창이 lookback보다 넓어지지 않게 한다.
    """
    end = floor_5min(until)
    raw_start = end - timedelta(minutes=lookback_minutes)
    start = floor_5min(raw_start)
    if start < raw_start:
        start += BIN
    out, t = [], start
    while t < end:
        out.append(t)
        t += BIN
    return out


def _load_links(conn: sqlite3.Connection) -> dict[str, list[_Link]]:
    """활성 구간의 링크(본선·측도 모두). segment_link가 없는 구간은 빈 목록."""
    rows = conn.execute(
        """
        SELECT s.segment_id, l.link_id, l.link_length_m, l.is_mainline, l.valid_from, l.valid_to
        FROM road_segment s
        LEFT JOIN segment_link l ON l.segment_id = s.segment_id
        WHERE s.is_active = 1
        ORDER BY s.seq, l.is_mainline DESC, l.seq
        """
    ).fetchall()
    out: dict[str, list[_Link]] = {}
    for r in rows:
        links = out.setdefault(r["segment_id"], [])
        if r["link_id"] is None:  # 링크가 없는 구간
            continue
        links.append(
            _Link(
                segment_id=r["segment_id"],
                link_id=r["link_id"],
                length_m=r["link_length_m"],
                is_mainline=bool(r["is_mainline"]),
                valid_from=parse_iso(r["valid_from"]),
                valid_to=parse_iso(r["valid_to"]) if r["valid_to"] else None,
            )
        )
    return out


def _frozen_keys(by_link: dict[str, list[_Obs]], repeat_count: int) -> set[tuple[str, datetime]]:
    """갱신 정지로 뺄 관측의 (link_id, 원본 시각).

    링크별로 원본 시각이 서로 다른 관측을 시간순으로 세므로, 같은 시각이 여러 수집원에서
    반복되어도 1건으로 센다(최근에 수집된 것을 대표값으로 쓴다).
    """
    out: set[tuple[str, datetime]] = set()
    for link_id, lst in by_link.items():
        lst.sort(key=lambda o: (o.source_timestamp, o.collected_at, o.row_id))
        seq: list[_Obs] = []
        for o in lst:
            if seq and seq[-1].source_timestamp == o.source_timestamp:
                seq[-1] = o
            else:
                seq.append(o)
        mask = rules.frozen_mask([o.speed for o in seq], repeat_count)
        out.update((link_id, o.source_timestamp) for o, m in zip(seq, mask) if m)
    return out


def _load_obs(
    conn: sqlite3.Connection,
    link_ids: set[str],
    start: datetime,
    first_bin: datetime,
    end_bin: datetime,
    until: datetime,
    repeat_count: int,
) -> tuple[dict[tuple[str, datetime], _Obs], int]:
    """(link_id, bin) → 사용할 관측 1건과 갱신 정지로 뺀 관측 수.

    `start`는 창의 첫 bin보다 `frozen_repeat_count x 5분` 앞이다. 갱신 정지는 링크별 연속 구간이므로
    창 앞쪽 관측도 판정에 필요하다.
    """
    if not link_ids:
        return {}, 0
    placeholders = ",".join("?" * len(link_ids))
    params = (*sorted(link_ids), to_iso(start), to_iso(end_bin))
    # source_timestamp는 to_iso 고정 형식 컬럼이라 문자열 범위 비교로 1차로 거른다. 최종 판정은 아래에서 datetime으로 한다.
    base = f"""
        FROM traffic_observation
        WHERE link_id IN ({placeholders})
          AND source_timestamp >= ? AND source_timestamp < ?
          AND quality_flag = 'ok' AND speed IS NOT NULL
    """
    # 'ok'인데 speed <= 0이면 수집기 플래그 오류다. 조화평균의 0 나눗셈으로 전체가 롤백되지 않게 빼고 경고한다.
    for r in conn.execute(f"SELECT link_id, source_timestamp, speed {base} AND speed <= 0", params):
        log.warning(
            "quality_flag='ok'인데 speed<=0인 관측을 집계에서 뺀다: link_id=%s source_timestamp=%s speed=%s",
            r["link_id"], r["source_timestamp"], r["speed"],
        )
    by_link: dict[str, list[_Obs]] = {}
    for r in conn.execute(
        f"SELECT id, link_id, source_timestamp, collected_at, speed {base} AND speed > 0", params
    ).fetchall():
        collected = parse_iso(r["collected_at"])
        if collected > until:  # 미래 정보 금지
            continue
        by_link.setdefault(r["link_id"], []).append(
            _Obs(r["id"], r["link_id"], parse_iso(r["source_timestamp"]), collected, float(r["speed"]))
        )

    frozen = _frozen_keys(by_link, repeat_count)

    best: dict[tuple[str, datetime], _Obs] = {}
    for lst in by_link.values():
        for o in lst:
            if (o.link_id, o.source_timestamp) in frozen:
                continue
            b = floor_5min(o.source_timestamp)
            if not (first_bin <= b < end_bin):
                continue
            key = (o.link_id, b)
            cur = best.get(key)
            if cur is None or (o.source_timestamp, o.collected_at, o.row_id) > (
                cur.source_timestamp, cur.collected_at, cur.row_id
            ):
                best[key] = o
    return best, len(frozen)


def _load_existing(
    conn: sqlite3.Connection, segment_ids: set[str], start_bin: datetime, end_bin: datetime
) -> dict[tuple[str, datetime], _Existing]:
    """DB에 이미 기록된 bin 행. 결측 보정의 직전 bin과 imputed 유지 판정에 쓴다."""
    if not segment_ids:
        return {}
    placeholders = ",".join("?" * len(segment_ids))
    rows = conn.execute(
        f"""
        SELECT segment_id, bin_time, speed, quality_flag, is_imputed
        FROM segment_traffic_5min
        WHERE segment_id IN ({placeholders}) AND bin_time >= ? AND bin_time < ?
        """,
        (*sorted(segment_ids), to_iso(start_bin), to_iso(end_bin)),
    ).fetchall()
    return {
        (r["segment_id"], parse_iso(r["bin_time"])): _Existing(
            r["speed"], r["quality_flag"], bool(r["is_imputed"])
        )
        for r in rows
    }


def _previous_values(
    sid: str, bin_time: datetime, max_bins: int,
    eff: dict[tuple[str, datetime], tuple[str, float | None]],
    existing: dict[tuple[str, datetime], _Existing],
) -> tuple[list[str], list[float | None]]:
    """현재 bin 바로 앞 `max_bins + 1`개 bin의 (quality_flag, speed) 목록. 오래된 것 → 최근.

    이번 실행에서 계산한 값이 있으면 그것을 쓰고, 창 앞의 bin은 DB 행을 쓴다. 행이 없는 bin은
    근거가 될 수 없게(`REAL_FLAGS` 밖) missing으로 센다.
    """
    flags: list[str] = []
    speeds: list[float | None] = []
    for k in range(max_bins + 1, 0, -1):
        e = eff.get((sid, bin_time - k * BIN))
        if e is None:
            old = existing.get((sid, bin_time - k * BIN))
            e = (old.quality_flag, old.speed) if old is not None else ("missing", None)
        flags.append(e[0])
        speeds.append(e[1])
    return flags, speeds


def _aggregate(
    expected: list[_Link], observed: list[tuple[_Link, _Obs]], min_coverage: float
) -> tuple[float | None, str]:
    """(speed, quality_flag). 판정은 `rules.segment_speed`가 한다."""
    return rules.segment_speed(
        [l.length_m for l in expected],
        [(l.length_m, o.speed) for l, o in observed],
        min_coverage,
    )


def run(until: datetime, conn: sqlite3.Connection | None = None, lookback_minutes: int = 60) -> int:
    """`until` 이전에 끝난 bin을 집계해 `segment_traffic_5min`에 기록하고 기록한 행 수를 돌려준다 (C-06).

    - `until`이 tz 정보가 없으면 `ValueError`.
    - `conn=None`이면 `database.db.connect()`로 열고 끝나면 닫는다. 받은 conn은 닫지 않는다.
    - 같은 입력으로 다시 실행해도 결과가 같다(`INSERT OR REPLACE`, imputed 유지 규칙). 함수 안에서 commit한다.
    """
    require_aware(until)
    own = conn is None
    if own:
        from database.db import connect

        conn = connect()
    assert conn is not None
    try:
        return _run(conn, until, lookback_minutes)
    finally:
        if own:
            conn.close()


def _run(conn: sqlite3.Connection, until: datetime, lookback_minutes: int) -> int:
    settings = get_settings()
    bins = _bins(until, lookback_minutes)
    if not bins:
        return 0
    links_by_seg = _load_links(conn)
    all_ids = {l.link_id for links in links_by_seg.values() for l in links}
    if not all_ids:
        return 0
    extra = settings.frozen_repeat_count * BIN  # 갱신 정지 판정용으로 창보다 더 읽는 구간
    obs, n_frozen = _load_obs(
        conn, all_ids, bins[0] - extra, bins[0], bins[-1] + BIN, until, settings.frozen_repeat_count
    )
    existing = _load_existing(
        conn, set(links_by_seg), bins[0] - (settings.ffill_max_bins + 1) * BIN, bins[-1] + BIN
    )
    processed_at = to_iso(until)
    eff: dict[tuple[str, datetime], tuple[str, float | None]] = {}  # 이번 실행의 확정된 bin 값
    rows = []
    n_imputed = 0

    for sid, links in links_by_seg.items():
        main_links = [l for l in links if l.is_mainline]
        side_links = [l for l in links if not l.is_mainline]
        for b in bins:
            main_expected = [l for l in main_links if l.valid_at(b)]
            main_obs = [(l, obs[(l.link_id, b)]) for l in main_expected if (l.link_id, b) in obs]
            speed, flag = _aggregate(main_expected, main_obs, settings.partial_min_coverage)

            side_expected = [l for l in side_links if l.valid_at(b)]
            side_obs = [(l, obs[(l.link_id, b)]) for l in side_expected if (l.link_id, b) in obs]
            side_speed, _ = _aggregate(side_expected, side_obs, settings.partial_min_coverage)

            is_imputed = 0
            if flag == "missing":
                kept = existing.get((sid, b))
                if kept is not None and kept.is_imputed and kept.speed is not None:
                    # 이미 기록한 imputed bin은 뒤에 되돌리지 않는다(브리프 결측 규칙 메모).
                    speed, flag, is_imputed = kept.speed, "imputed", 1
                else:
                    flags, speeds = _previous_values(sid, b, settings.ffill_max_bins, eff, existing)
                    i = rules.fill_source(flags, settings.ffill_max_bins)
                    if i is not None and speeds[i] is not None:
                        speed, flag, is_imputed = speeds[i], "imputed", 1
            eff[(sid, b)] = (flag, speed)
            if flag == "imputed":
                n_imputed += 1

            # available_at: 사용한 관측(본선+측도)의 최대 collected_at. missing·imputed는 bin 끝 시각(C-01 v1.2).
            if flag in ("missing", "imputed"):
                available_at = b + BIN
            else:
                available_at = max(o.collected_at for _, o in (*main_obs, *side_obs))
            rows.append(
                (sid, to_iso(b), to_iso(available_at), speed, side_speed, None,
                 len(main_expected), len(main_obs), is_imputed, flag, processed_at)
            )
    try:
        conn.executemany(
            """
            INSERT OR REPLACE INTO segment_traffic_5min
                (segment_id, bin_time, available_at, speed, speed_side, volume,
                 n_links_expected, n_links_observed, is_imputed, quality_flag, processed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    log.info(
        "구간 집계 %d행 (bin %s ~ %s, imputed %d, 갱신 정지 제외 관측 %d)",
        len(rows), to_iso(bins[0]), to_iso(bins[-1]), n_imputed, n_frozen,
    )
    return len(rows)
