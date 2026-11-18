"""구간 시드(`config.segments.SEGMENTS`)와 링크 매핑 CSV를 DB에 UPSERT한다 (SPEC 3.5).

- `road_segment`: segment_id 기준 UPSERT. `is_active`는 건드리지 않는다.
- `segment_link`: UNIQUE(source, link_id, valid_from) 기준 UPSERT.
- CSV 빈 값은 NULL로 넣는다(길이 모름 ≠ 0). NOT NULL 컬럼이 비어 있으면 `ValueError`.
- `valid_from`은 KST ISO(`YYYY-MM-DDTHH:MM:SS+09:00`)로 정규화한다. 오프셋이 없으면 `ValueError`.
- `road_segment.distance_m` = 유효(valid_to IS NULL) 본선 링크 길이 합. 길이 NULL이 하나라도 있거나
  링크가 없으면 NULL.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from common.logsetup import get_logger
from common.timeutil import parse_iso, to_iso

log = get_logger("scripts.load_segments")

_REQUIRED = ("segment_id", "seq", "link_id", "source", "is_mainline", "valid_from")
_COLUMNS = ("segment_id", "seq", "link_id", "source", "link_length_m", "is_mainline", "nodelink_ver", "valid_from")


def _read_links(links_csv: Path) -> list[dict]:
    """CSV를 읽어 타입을 맞춘 행 목록을 돌려준다. 빈 값은 None."""
    rows: list[dict] = []
    with open(links_csv, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing_cols = set(_COLUMNS) - set(reader.fieldnames or [])
        if missing_cols:
            raise ValueError(f"{links_csv}: 필요한 컬럼이 없다: {sorted(missing_cols)}")
        for lineno, raw in enumerate(reader, start=2):
            row = {k: (raw.get(k) or "").strip() or None for k in _COLUMNS}
            empty = [k for k in _REQUIRED if row[k] is None]
            if empty:
                raise ValueError(f"{links_csv}:{lineno}: 필수 값이 비어 있다: {empty}")
            try:
                row["seq"] = int(row["seq"])
                if row["is_mainline"] not in ("0", "1"):
                    raise ValueError(f"is_mainline은 0 또는 1이어야 한다: {row['is_mainline']!r}")
                row["is_mainline"] = int(row["is_mainline"])
                if row["link_length_m"] is not None:
                    row["link_length_m"] = float(row["link_length_m"])
                # 표기가 달라도 같은 시각이면 같은 UPSERT 키가 되도록 KST ISO로 정규화한다.
                # 오프셋이 없으면 parse_iso가 ValueError를 낸다(날짜만 있는 값 포함).
                row["valid_from"] = to_iso(parse_iso(row["valid_from"]))
            except ValueError as e:
                raise ValueError(f"{links_csv}:{lineno}: {e}") from e
            rows.append(row)
    return rows


def load(conn: sqlite3.Connection, segments: list[dict], links_csv: Path) -> tuple[int, int]:
    """구간과 링크를 UPSERT하고 (구간 수, 링크 수)를 돌려준다. 다시 실행해도 결과가 같다.

    트랜잭션 동작:
    - CSV 검증(필수 값, `is_mainline` 0/1, `valid_from` 오프셋 포함 ISO8601)을 DB 쓰기 전에 끝낸다.
      검증 실패는 `ValueError`이며 DB에 아무것도 쓰지 않는다.
    - 구간·링크 UPSERT와 `distance_m` 갱신을 한 트랜잭션으로 실행하고 끝에서 commit한다.
      도중 오류(예: 없는 segment_id로 인한 FK 위반 `sqlite3.IntegrityError`)가 나면 rollback 후
      예외를 다시 던진다. 따라서 호출 전에 커밋하지 않은 변경이 conn에 있으면 함께 롤백된다.
    """
    links = _read_links(Path(links_csv))
    try:
        conn.executemany(
            """
            INSERT INTO road_segment (segment_id, road_name, start_node, end_node, direction, seq, is_target)
            VALUES (:segment_id, :road_name, :start_node, :end_node, :direction, :seq, :is_target)
            ON CONFLICT (segment_id) DO UPDATE SET
                road_name = excluded.road_name,
                start_node = excluded.start_node,
                end_node = excluded.end_node,
                direction = excluded.direction,
                seq = excluded.seq,
                is_target = excluded.is_target
            """,
            segments,
        )
        conn.executemany(
            """
            INSERT INTO segment_link
                (segment_id, link_id, source, seq, link_length_m, is_mainline, nodelink_ver, valid_from)
            VALUES
                (:segment_id, :link_id, :source, :seq, :link_length_m, :is_mainline, :nodelink_ver, :valid_from)
            ON CONFLICT (source, link_id, valid_from) DO UPDATE SET
                segment_id = excluded.segment_id,
                seq = excluded.seq,
                link_length_m = excluded.link_length_m,
                is_mainline = excluded.is_mainline,
                nodelink_ver = excluded.nodelink_ver
            """,
            links,
        )
        # 길이를 하나라도 모르면 합계도 모른다 → NULL. 링크가 없으면 SUM이 NULL.
        conn.execute(
            """
            UPDATE road_segment SET distance_m = (
                SELECT CASE WHEN COUNT(*) = COUNT(l.link_length_m) THEN SUM(l.link_length_m) END
                FROM segment_link l
                WHERE l.segment_id = road_segment.segment_id
                  AND l.is_mainline = 1
                  AND l.valid_to IS NULL
            )
            """
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    log.info("구간 %d개, 링크 %d개 적재", len(segments), len(links))
    return len(segments), len(links)
