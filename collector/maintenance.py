"""수집기 정비 도구 (D-COL-05, D-COL-06). 실행:
`python -m collector.maintenance purge --raw <gz> [--apply]` · `python -m collector.maintenance prune-raw [--apply]`.

`purge`: C-02 v2 저장 범위(창원대로) 이전에 쌓인 범위 밖 관측 행을 정리한다. `traffic_observation` 외의
테이블은 건드리지 않는다. 기본은 dry-run(숫자만 출력)이고 `--apply`일 때만 삭제 후 VACUUM한다.
DB 백업은 자동이 아니므로 `--apply` 전에 수동으로 백업해야 한다.
`prune-raw`: `raw_keep_days`보다 오래된 원본 날짜 폴더를 정리한다(C-06 v2.2). 기본 dry-run, `--apply`로 삭제.
"""

from __future__ import annotations

import argparse
import gzip
import re
import shutil
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

from collector.paths import resolve_path
from collector.runner import _target_links
from common.logsetup import get_logger
from common.timeutil import now_kst, require_aware
from config.settings import Settings

log = get_logger(__name__)

_KEEP_TABLE = "temp._purge_keep"
_DATE_DIR_RE = re.compile(r"\d{8}")


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
        try:
            conn.execute(f"DROP TABLE IF EXISTS {_KEEP_TABLE}")
        except Exception as e:
            # 임시 테이블 정리 실패가 원래 예외를 가리지 않게 한다.
            log.warning("purge: 임시 테이블 정리 실패: %s", e)
    log.info("purge %s: %s", "dry-run" if dry_run else "apply", stats)
    return stats


def prune_raw(now: datetime, settings: Settings | None = None, *, dry_run: bool = True) -> int:
    """`raw_dir/<source>/<YYYYMMDD>/` 날짜 폴더 중 `raw_keep_days`보다 오래된 것을 지운다 (C-06 v2.2).

    - 상대 `raw_dir`은 저장소 루트 기준으로 해석한다(`database.db.connect`와 같은 규칙).
      `raw_dir`이 빈 문자열·공백이면 `ValueError`를 낸다(아무것도 지우지 않는다).
    - 폴더 이름이 8자리 날짜(YYYYMMDD)가 아니거나 실제 날짜로 읽히지 않으면 건드리지 않는다.
    - 오늘·어제 날짜 폴더는 `raw_keep_days`와 무관하게 보존한다(설정 실수 방지 안전장치).
    - `dry_run=True`(기본)이면 아무것도 지우지 않고 지울 파일 수만 센다.
    - 한 폴더의 삭제가 실패해도 나머지를 계속 지우고, 실패는 로그 경고로 남긴다.
    - 반환: 지우거나(apply) 지울(dry-run) 파일 수. 삭제에 실패한 폴더의 파일은 세지 않는다.
    `now`가 timezone 정보 없는 datetime이면 `ValueError`를 낸다.
    """
    require_aware(now)
    if settings is None:
        from config.settings import get_settings

        settings = get_settings()
    raw_dir_value = settings.raw_dir
    if raw_dir_value is None or not str(raw_dir_value).strip():
        raise ValueError(f"raw_dir이 비어 있다. 삭제 대상을 정할 수 없다: {raw_dir_value!r}")
    cutoff = (now - timedelta(days=settings.raw_keep_days)).date()
    floor = (now - timedelta(days=1)).date()  # 어제 이후는 설정과 무관하게 보존한다
    raw_dir = resolve_path(raw_dir_value)
    mode = "dry-run" if dry_run else "apply"
    if not raw_dir.is_dir():
        log.info("prune-raw %s: raw_dir이 없다: %s", mode, raw_dir)
        return 0

    files = 0
    folders = 0
    failed = 0
    for source_dir in sorted(p for p in raw_dir.iterdir() if p.is_dir()):
        for date_dir in sorted(p for p in source_dir.iterdir() if p.is_dir()):
            if _DATE_DIR_RE.fullmatch(date_dir.name) is None:
                continue  # 날짜 폴더가 아니면 건드리지 않는다
            try:
                d = datetime.strptime(date_dir.name, "%Y%m%d").date()
            except ValueError:
                continue  # 8자리지만 실제 날짜가 아니면 건드리지 않는다
            if not (d < cutoff and d < floor):
                continue
            try:
                n = sum(1 for f in date_dir.rglob("*") if f.is_file())
                if not dry_run:
                    shutil.rmtree(date_dir)
                files += n
                folders += 1
                action = "삭제 예정" if dry_run else "삭제"
                log.info("prune-raw %s: %s %s (파일 %d개)", mode, action, date_dir, n)
            except OSError as e:
                failed += 1
                log.warning("prune-raw: 폴더 삭제 실패, 나머지를 계속 지운다: %s: %s", date_dir, e)
    log.info(
        "prune-raw %s: 폴더 %d개, 파일 %d개, 실패 %d개 (기준 %s 이전, %s 이후 보존)",
        mode, folders, files, failed, cutoff, floor,
    )
    return files


def main(argv: list[str] | None = None) -> int:
    """`purge --raw <gz> [--apply]` · `prune-raw [--apply]`. 기본은 dry-run으로 숫자만 출력한다."""
    parser = argparse.ArgumentParser(prog="python -m collector.maintenance", description="수집기 정비 도구")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("purge", help="저장 범위 밖 관측 행 정리")
    p.add_argument("--raw", type=Path, required=True, help="저장 범위 링크를 뽑을 ITS 원본 .xml.gz")
    p.add_argument("--apply", action="store_true", help="실제로 삭제하고 VACUUM한다(없으면 dry-run)")
    pr = sub.add_parser("prune-raw", help="오래된 원본 날짜 폴더 정리 (raw_keep_days)")
    pr.add_argument("--apply", action="store_true", help="실제로 삭제한다(없으면 dry-run)")
    args = parser.parse_args(argv)

    from config.settings import get_settings

    settings = get_settings()

    if args.command == "prune-raw":
        files = prune_raw(now_kst(), settings, dry_run=not args.apply)
        print(f"{'적용' if args.apply else 'dry-run'}: 파일 {files}개")
        return 0

    from database.db import connect  # C-06

    keep_ids = store_scope_link_ids(args.raw, settings)
    print(f"저장 범위 링크(원본 기준): {len(keep_ids)}개 {settings.its_store_road_names}")
    print("주의: DB 백업은 자동이 아니다. --apply 전에 DB 파일을 수동으로 백업하라.")
    if args.apply:
        print(f"대상 DB: {resolve_path(settings.db_path).resolve()}")
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
