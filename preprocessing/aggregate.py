"""5분 구간 집계 v0 (SPEC 6.2 축소판, Slice 0 Task 6).

`traffic_observation`(링크 단위 관측)을 읽어 `segment_traffic_5min`(구간 x 5분 bin)에 쓴다.

v0 규칙:
- 대상 bin: `[floor_5min(until) - lookback, floor_5min(until))`. 끝난 bin만 처리하므로 미완성 bin은 쓰지 않는다.
  lookback이 5의 배수가 아니면 시작을 다음 5분 경계로 올린다(창이 lookback보다 넓어지지 않음).
- 링크: bin 시작 시각에 유효(`valid_from <= bin < valid_to 또는 NULL`)한 본선(`is_mainline=1`) 링크.
  측도(0) 링크는 v0에서 집계하지 않는다(`speed_side=NULL`, Slice 1).
- 관측 대조는 `link_id`로만 한다(`segment_link.source`는 링크 ID 체계 출처라 거르지 않는다, C-01 v1.1).
- 링크별 관측: 같은 bin, `collected_at <= until`, `quality_flag='ok'`, `speed > 0` 중
  (ok인데 speed<=0인 행은 경고 로그 후 제외)
  `source_timestamp`가 가장 늦은 1건. 미래에 수집된 관측은 쓰지 않는다.
- 구간 속도: 길이가 모두 있으면 거리 가중 조화평균(`ok`/`partial`), 길이 NULL이 섞이면 단순 평균
  (`unweighted`), 관측 0개면 NULL(`missing`). 결측을 0으로 바꾸지 않는다.
- v0에서는 SPEC 6.2의 70% 부분 관측 기준과 6.3 forward fill을 적용하지 않는다(Slice 1).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from common.logsetup import get_logger
from common.timeutil import floor_5min, parse_iso, require_aware, to_iso

log = get_logger("preprocessing.aggregate")

BIN = timedelta(minutes=5)  # floor_5min과 같은 bin 크기


@dataclass(frozen=True)
class _Link:
    segment_id: str
    link_id: str
    length_m: float | None
    valid_from: datetime
    valid_to: datetime | None

    def valid_at(self, t: datetime) -> bool:
        return self.valid_from <= t and (self.valid_to is None or t < self.valid_to)


@dataclass(frozen=True)
class _Obs:
    source_timestamp: datetime
    collected_at: datetime
    speed: float


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
    rows = conn.execute(
        """
        SELECT s.segment_id, l.link_id, l.link_length_m, l.valid_from, l.valid_to
        FROM road_segment s
        LEFT JOIN segment_link l ON l.segment_id = s.segment_id AND l.is_mainline = 1
        WHERE s.is_active = 1
        ORDER BY s.seq, l.seq
        """
    ).fetchall()
    out: dict[str, list[_Link]] = {}
    for r in rows:
        links = out.setdefault(r["segment_id"], [])
        if r["link_id"] is None:  # 본선 링크가 없는 구간
            continue
        links.append(
            _Link(
                segment_id=r["segment_id"],
                link_id=r["link_id"],
                length_m=r["link_length_m"],
                valid_from=parse_iso(r["valid_from"]),
                valid_to=parse_iso(r["valid_to"]) if r["valid_to"] else None,
            )
        )
    return out


def _load_obs(
    conn: sqlite3.Connection, link_ids: set[str], first_bin: datetime, end_bin: datetime, until: datetime
) -> dict[tuple[str, datetime], _Obs]:
    """(link_id, bin) → 사용할 관측 1건."""
    if not link_ids:
        return {}
    placeholders = ",".join("?" * len(link_ids))
    params = (*sorted(link_ids), to_iso(first_bin), to_iso(end_bin))
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
    rows = conn.execute(
        f"SELECT link_id, source_timestamp, collected_at, speed {base} AND speed > 0", params
    ).fetchall()
    best: dict[tuple[str, datetime], _Obs] = {}
    for r in rows:
        ts, collected = parse_iso(r["source_timestamp"]), parse_iso(r["collected_at"])
        if collected > until:  # 미래 정보 금지
            continue
        b = floor_5min(ts)
        if not (first_bin <= b < end_bin):
            continue
        obs = _Obs(ts, collected, float(r["speed"]))
        key = (r["link_id"], b)
        cur = best.get(key)
        if cur is None or (obs.source_timestamp, obs.collected_at) > (cur.source_timestamp, cur.collected_at):
            best[key] = obs
    return best


def _segment_value(observed: list[tuple[_Link, _Obs]], n_expected: int) -> tuple[float | None, str]:
    """(speed, quality_flag)."""
    if not observed:
        return None, "missing"
    if any(link.length_m is None for link, _ in observed):
        return sum(o.speed for _, o in observed) / len(observed), "unweighted"
    total_len = sum(link.length_m for link, _ in observed)  # type: ignore[misc]
    total_time = sum(link.length_m / o.speed for link, o in observed)  # type: ignore[operator]
    flag = "ok" if len(observed) == n_expected else "partial"
    return total_len / total_time, flag


def run(until: datetime, conn: sqlite3.Connection | None = None, lookback_minutes: int = 60) -> int:
    """`until` 이전에 끝난 bin을 집계해 `segment_traffic_5min`에 기록하고 기록한 행 수를 돌려준다 (C-06).

    - `until`이 tz 정보가 없으면 `ValueError`.
    - `conn=None`이면 `database.db.connect()`로 열고 끝나면 닫는다. 받은 conn은 닫지 않는다.
    - 같은 입력으로 다시 실행해도 결과가 같다(`INSERT OR REPLACE`). 함수 안에서 commit한다.
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
    bins = _bins(until, lookback_minutes)
    if not bins:
        return 0
    links_by_seg = _load_links(conn)
    all_ids = {l.link_id for links in links_by_seg.values() for l in links}
    obs = _load_obs(conn, all_ids, bins[0], bins[-1] + BIN, until)
    processed_at = to_iso(until)

    rows = []
    for sid, links in links_by_seg.items():
        for b in bins:
            expected = [l for l in links if l.valid_at(b)]
            observed = [(l, obs[(l.link_id, b)]) for l in expected if (l.link_id, b) in obs]
            speed, flag = _segment_value(observed, len(expected))
            available_at = max(o.collected_at for _, o in observed) if observed else b + BIN
            rows.append(
                (sid, to_iso(b), to_iso(available_at), speed, None, None,
                 len(expected), len(observed), 0, flag, processed_at)
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
    log.info("구간 집계 %d행 (bin %s ~ %s)", len(rows), to_iso(bins[0]), to_iso(bins[-1]))
    return len(rows)
