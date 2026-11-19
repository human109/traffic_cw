"""`traffic_observation` 정비 도구 (D-COL-05). 실행: `python -m collector.maintenance purge --raw <gz> [--apply]`.

C-02 v2 저장 범위(창원대로) 이전에 쌓인 범위 밖 행을 정리한다. `traffic_observation` 외의 테이블은 건드리지 않는다.
기본은 dry-run(숫자만 출력)이고 `--apply`일 때만 삭제 후 VACUUM한다. 실행 전에 DB를 백업한다.
"""

from __future__ import annotations

import argparse
import gzip
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from collector.runner import _target_links
from common.logsetup import get_logger
from common.timeutil import now_kst, require_aware
from config.settings import Settings

log = get_logger(__name__)

_KEEP_TABLE = "temp._purge_keep"


def store_scope_link_ids(raw_file: Path, settings: Settings) -> set[str]:
    """gzip 원본 ITS XML에서 `roadName ∈ settings.its_store_road_names`인 item의 linkId 집합.

    XML이 아니거나 gzip이 아니면 예외(`ValueError`·`OSError`)를 낸다.
    """
    body = gzip.decompress(Path(raw_file).read_bytes())
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise ValueError(f"원본 XML을 읽을 수 없다: {raw_file}: {e}") from e
    allowed = set(settings.its_store_road_names)
    out: set[str] = set()
    for item in root.findall("body/items/item"):
        road = (item.findtext("roadName") or "").strip()
        link_id = (item.findtext("linkId") or "").strip()
        if road in allowed and link_id:
            out.add(link_id)
    return out


def purge_outside_scope(
    conn: sqlite3.Connection,
    keep_link_ids: set[str],
    *,
    dry_run: bool = True,
    now: datetime | None = None,
) -> dict[str, int]:
    """`keep_link_ids`에도, `now` 시점에 유효한 `segment_link`에도 없는 link_id의 관측 행을 센다/지운다.

    반환: `{"total", "keep", "delete", "keep_links"}` (모두 실행 전 기준 행 수·고유 링크 수).
    - `dry_run=True`(기본)이면 아무것도 지우지 않는다.
    - `dry_run=False`이면 한 트랜잭션으로 지우고 commit한다. 실패하면 rollback하고 예외를 다시 낸다.
    - `keep_link_ids`가 비어 있으면 `ValueError` (전부 지우는 사고 방지).
    주의: 끝에서 commit 또는 rollback하므로 호출 전 conn의 미커밋 변경도 함께 확정·취소된다.
    """
    if not keep_link_ids:
        raise ValueError("keep_link_ids가 비어 있다. 전체 삭제를 막기 위해 중단한다")
    now = now if now is not None else now_kst()
    require_aware(now)

    keep = set(keep_link_ids) | _target_links(conn, now)
    in_keep = f"link_id IN (SELECT link_id FROM {_KEEP_TABLE})"
    try:
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS _purge_keep (link_id TEXT PRIMARY KEY)")
        conn.execute(f"DELETE FROM {_KEEP_TABLE}")
        conn.executemany(f"INSERT INTO {_KEEP_TABLE} (link_id) VALUES (?)", [(x,) for x in keep])
        total = conn.execute("SELECT COUNT(*) FROM traffic_observation").fetchone()[0]
        keep_rows, keep_links = conn.execute(
            f"SELECT COUNT(*), COUNT(DISTINCT link_id) FROM traffic_observation WHERE {in_keep}"
        ).fetchone()
        stats = {"total": total, "keep": keep_rows, "delete": total - keep_rows, "keep_links": keep_links}
        if dry_run:
            conn.rollback()
        else:
            deleted = conn.execute(f"DELETE FROM traffic_observation WHERE NOT ({in_keep})").rowcount
            if deleted != stats["delete"]:
                raise RuntimeError(f"삭제 행 수가 예상과 다르다: {deleted} != {stats['delete']}")
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute(f"DROP TABLE IF EXISTS {_KEEP_TABLE}")
    log.info("purge %s: %s", "dry-run" if dry_run else "apply", stats)
    return stats


def main(argv: list[str] | None = None) -> int:
    """`purge --raw <gz> [--apply]`. 기본은 dry-run으로 숫자만 출력한다."""
    parser = argparse.ArgumentParser(prog="python -m collector.maintenance", description="traffic_observation 정비")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("purge", help="저장 범위 밖 관측 행 정리")
    p.add_argument("--raw", type=Path, required=True, help="저장 범위 링크를 뽑을 ITS 원본 .xml.gz")
    p.add_argument("--apply", action="store_true", help="실제로 삭제하고 VACUUM한다(없으면 dry-run)")
    args = parser.parse_args(argv)

    from config.settings import get_settings
    from database.db import connect  # C-06

    settings = get_settings()
    keep_ids = store_scope_link_ids(args.raw, settings)
    print(f"저장 범위 링크(원본 기준): {len(keep_ids)}개 {settings.its_store_road_names}")
    conn = connect()
    try:
        stats = purge_outside_scope(conn, keep_ids, dry_run=not args.apply)
        print(f"{'적용' if args.apply else 'dry-run'}: {stats}")
        if args.apply:
            conn.execute("VACUUM")
            print("VACUUM 완료")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
