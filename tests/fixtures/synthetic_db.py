"""synthetic: 테스트 전용 합성 DB. 실제 교통 데이터가 아니며 운영 DB·화면에 쓰지 않는다 (AGENTS.md 6장 1).

계약 DDL(`docs/contracts/C-01-schema.sql`)을 직접 실행해 만든다. database 모듈에 의존하지 않으므로
모듈들을 병렬로 개발할 수 있다.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from common.timeutil import KST, to_iso

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DDL = ROOT / "docs" / "contracts" / "C-01-schema.sql"

SOURCE = "synthetic"
VALID_FROM = "2026-01-01T00:00:00+09:00"
DAY_START = datetime(2026, 11, 16, 6, 30, tzinfo=KST)  # 월요일
DAY_END = datetime(2026, 11, 16, 8, 0, tzinfo=KST)
COLLECT_DELAY = timedelta(seconds=40)

SEGMENTS = [
    # segment_id, seq, start, end, is_target
    ("S0", 0, "합성 시작점", "합성 A", 0),
    ("S1", 1, "합성 A", "합성 B", 1),
    ("S2", 2, "합성 B", "합성 C", 1),
    ("S3", 3, "합성 C", "합성 D", 1),
]

# segment_id, seq, link_id, length_m (None = 길이 모름)
LINKS = [
    ("S0", 1, "SYN0000000", 600.0),
    ("S1", 1, "SYN0000001", 500.0),
    ("S1", 2, "SYN0000002", 700.0),
    ("S2", 1, "SYN0000003", 1000.0),
    ("S3", 1, "SYN0000004", 800.0),
    ("S3", 2, "SYN0000005", None),
]

GAP_LINK = "SYN0000003"
GAP_START = datetime(2026, 11, 16, 7, 20, tzinfo=KST)
GAP_END = datetime(2026, 11, 16, 7, 40, tzinfo=KST)  # 포함
ZERO_POINT = ("SYN0000002", datetime(2026, 11, 16, 7, 10, tzinfo=KST))
OUT_OF_RANGE_POINT = ("SYN0000004", datetime(2026, 11, 16, 7, 15, tzinfo=KST))


def link_number(link_id: str) -> int:
    return int(link_id[-1])


def fixture_speed(link_id: str, ts: datetime) -> float:
    """합성 속도 공식: 60 - 0.4 x (06:30부터 경과 분) + 링크 번호."""
    minutes = (ts - DAY_START).total_seconds() / 60
    return 60 - 0.4 * minutes + link_number(link_id)


def _timestamps() -> list[datetime]:
    out, ts = [], DAY_START
    while ts <= DAY_END:
        out.append(ts)
        ts += timedelta(minutes=5)
    return out


def build_fixture_db(path: Path) -> Path:
    """합성 DB를 `path`에 만들고 경로를 돌려준다."""
    conn = sqlite3.connect(path)
    try:
        conn.executescript(CONTRACT_DDL.read_text(encoding="utf-8"))
        conn.executemany(
            "INSERT INTO road_segment (segment_id, road_name, start_node, end_node, direction, seq, is_target)"
            " VALUES (?, '합성도로', ?, ?, '합성 방향', ?, ?)",
            [(sid, start, end, seq, tgt) for sid, seq, start, end, tgt in SEGMENTS],
        )
        conn.executemany(
            "INSERT INTO segment_link (segment_id, link_id, source, seq, link_length_m, is_mainline, nodelink_ver, valid_from)"
            " VALUES (?, ?, ?, ?, ?, 1, 'synthetic', ?)",
            [(sid, lid, SOURCE, seq, length, VALID_FROM) for sid, seq, lid, length in LINKS],
        )
        rows = []
        for ts in _timestamps():
            for _sid, _seq, lid, _len in LINKS:
                if lid == GAP_LINK and GAP_START <= ts <= GAP_END:
                    continue
                speed, flag = fixture_speed(lid, ts), "ok"
                if (lid, ts) == ZERO_POINT:
                    speed, flag = 0.0, "default_value"
                elif (lid, ts) == OUT_OF_RANGE_POINT:
                    speed, flag = 200.0, "out_of_range"
                rows.append((SOURCE, lid, to_iso(ts), to_iso(ts + COLLECT_DELAY), speed, flag))
        conn.executemany(
            "INSERT INTO traffic_observation (source, link_id, source_timestamp, collected_at, speed, quality_flag)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    return path
