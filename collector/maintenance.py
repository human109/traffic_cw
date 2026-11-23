"""수집기 정비 도구 (D-COL-05, D-COL-06, W-03). 실행:
`purge --raw <gz> [--apply]` · `prune-raw [--apply]` · `reload-raw --from <날짜> --to <날짜> --road <도로> [--apply]`.

`purge`: C-02 v2 저장 범위 이전에 쌓인 범위 밖 관측 행을 정리한다. `traffic_observation` 외의
테이블은 건드리지 않는다. 기본은 dry-run(숫자만 출력)이고 `--apply`일 때만 삭제 후 VACUUM한다.
DB 백업은 자동이 아니므로 `--apply` 전에 수동으로 백업해야 한다.
`prune-raw`: `raw_keep_days`보다 오래된 원본 날짜 폴더를 정리한다(C-06 v2.2). 기본 dry-run, `--apply`로 삭제.
`reload-raw`: 보관 중인 원본 gz에서 지정 도로 관측을 다시 넣는다(C-06 v2.3, C-02 v2.2). 기본 dry-run, `--apply`로 삽입.
"""

from __future__ import annotations

import argparse
import gzip
import re
import shutil
import sqlite3
import xml.etree.ElementTree as ET
import zlib
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

from collector.its import ItsAdapter
from collector.paths import resolve_path
from collector.runner import _target_links
from collector.store import insert_observations, raw_file_ref
from common.logsetup import get_logger
from common.records import ObservationRecord
from common.timeutil import now_kst, parse_compact_kst, require_aware, to_iso
from config.settings import Settings

log = get_logger(__name__)

_KEEP_TABLE = "temp._purge_keep"
_RELOAD_TABLE = "temp._reload_keys"
_DATE_DIR_RE = re.compile(r"\d{8}")
_TIME_FILE_RE = re.compile(r"\d{6}")


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


def _scan_raw(
    start: date, end: date, roads: set[str], settings: Settings
) -> tuple[list[ObservationRecord], int]:
    """원본 gz를 날짜순으로 읽어 지정 도로 후보 레코드와 읽은 파일 수를 돌려준다.

    파싱·quality_flag 규칙은 기존 ITS 어댑터를 재사용한다. 깨진 gz·XML은 경고 후 건너뛴다.
    `collected_at`은 파일 이름의 수집 시각(KST, 초 포함)이다 — 재적재 실행 시각을 쓰면
    as-of 규칙(미래 정보 금지)이 깨진다(C-02 v2.2).
    """
    adapter = ItsAdapter(settings)
    raw_dir = resolve_path(settings.raw_dir) / "its"
    records: list[ObservationRecord] = []
    files = 0
    d = start
    while d <= end:
        day_dir = raw_dir / d.strftime("%Y%m%d")
        if day_dir.is_dir():
            for path in sorted(day_dir.glob("*.xml.gz")):
                if _TIME_FILE_RE.fullmatch(path.name.removesuffix(".xml.gz")) is None:
                    log.warning("reload-raw: 파일 이름이 HHMMSS.xml.gz 형식이 아니어서 건너뛴다: %s", path)
                    continue
                try:
                    body = gzip.decompress(path.read_bytes())
                    file_time = parse_compact_kst(d.strftime("%Y%m%d") + path.name[:6])
                    parsed = adapter.parse(body, file_time)
                except (OSError, EOFError, ValueError, zlib.error) as e:
                    # 절단 gz(EOFError)·손상 deflate(zlib.error)·헤더 손상(BadGzipFile=OSError)·XML 오류(ValueError)
                    log.warning("reload-raw: 원본을 읽지 못해 건너뛴다: %s: %s", path, e)
                    continue
                files += 1
                ref = raw_file_ref(path)
                records.extend(replace(r, raw_file=ref) for r in parsed if r.road_name in roads)
        d += timedelta(days=1)
    return records, files


def _count_missing_keys(conn: sqlite3.Connection, records: list[ObservationRecord]) -> int:
    """아직 `traffic_observation`에 없는 (source, link_id, source_timestamp) 키 수."""
    if not records:
        return 0
    keys = {(r.source, r.link_id, to_iso(r.source_timestamp)) for r in records}
    conn.execute(f"CREATE TEMP TABLE IF NOT EXISTS {_RELOAD_TABLE} (source TEXT, link_id TEXT, source_timestamp TEXT)")
    conn.execute(f"DELETE FROM {_RELOAD_TABLE}")
    conn.executemany(
        f"INSERT INTO {_RELOAD_TABLE} (source, link_id, source_timestamp) VALUES (?, ?, ?)",
        sorted(keys),
    )
    try:
        return conn.execute(
            f"SELECT COUNT(*) FROM {_RELOAD_TABLE} k WHERE NOT EXISTS ("
            " SELECT 1 FROM traffic_observation t WHERE t.source = k.source"
            "   AND t.link_id = k.link_id AND t.source_timestamp = k.source_timestamp)"
        ).fetchone()[0]
    finally:
        try:
            conn.execute(f"DROP TABLE IF EXISTS {_RELOAD_TABLE}")
        except Exception as e:  # 임시 테이블 정리 실패가 원래 값을 가리지 않게 한다
            log.warning("reload-raw: 임시 테이블 정리 실패: %s", e)


def reload_raw(
    start: date,
    end: date,
    road_names: Sequence[str],
    conn: sqlite3.Connection | None = None,
    settings: Settings | None = None,
    *,
    dry_run: bool = True,
) -> int:
    """보관 중인 원본 gz에서 지정 도로 관측을 다시 `traffic_observation`에 넣는다 (C-06 v2.3, C-02 v2.2).

    - `raw_dir/its/<YYYYMMDD>/<HHMMSS>.xml.gz`를 날짜 양끝을 포함해 날짜순으로 읽는다.
    - `collected_at`은 파일 이름의 수집 시각(KST, 초 포함)이다. `source_timestamp`는 원본 값,
      `raw_file`은 그 원본의 저장소 루트 기준 상대 경로다.
    - 파싱·quality_flag 규칙은 기존 ITS 어댑터를 재사용한다. 지정 도로(`roadName`) item만 넣는다.
    - `INSERT OR IGNORE`(UNIQUE source, link_id, source_timestamp), 한 트랜잭션. `collection_log`는
      쓰지 않는다. 깨진 gz·XML은 경고 로그를 남기고 건너뛴다(나머지는 계속).
    - `dry_run=True`(기본)이면 아무것도 넣지 않고 넣을(아직 없는 키) 행 수를 반환한다.
    - 반환: 넣었거나(apply) 넣을(dry-run) 행 수.
    - `start > end`이거나 `road_names`가 비어 있으면 `ValueError`.
    주의: 끝에서 apply는 commit, dry-run은 rollback하므로 호출 전 conn의 미커밋 변경도 함께 확정·취소된다.
    """
    rows, _files = _reload_raw(start, end, road_names, conn=conn, settings=settings, dry_run=dry_run)
    return rows


def _reload_raw(
    start: date,
    end: date,
    road_names: Sequence[str],
    conn: sqlite3.Connection | None = None,
    settings: Settings | None = None,
    *,
    dry_run: bool = True,
) -> tuple[int, int]:
    """`reload_raw`의 본문. (행 수, 읽은 파일 수)를 돌려준다. CLI가 파일 수도 출력하기 위해 둔다."""
    if end < start:
        raise ValueError(f"날짜 범위가 올바르지 않다: {end} < {start}")
    roads = set(road_names)
    if not roads:
        raise ValueError("road_names가 비어 있다. 넣을 도로를 지정해야 한다")
    if settings is None:
        from config.settings import get_settings

        settings = get_settings()
    candidates, files = _scan_raw(start, end, roads, settings)
    # 같은 (source, link_id, source_timestamp)가 여러 파일에 있으면 첫 파일(시간순)만 남긴다.
    deduped: dict[tuple[str, str, str], ObservationRecord] = {}
    for r in candidates:
        deduped.setdefault((r.source, r.link_id, to_iso(r.source_timestamp)), r)
    batch = list(deduped.values())

    own_conn = conn is None
    if conn is None:
        from database.db import connect  # C-06

        conn = connect()
    mode = "dry-run" if dry_run else "apply"
    try:
        if dry_run:
            rows = _count_missing_keys(conn, batch)
            conn.rollback()  # 임시 테이블 DML이 연 암시 트랜잭션을 닫는다(purge dry-run과 같다)
        else:
            rows = insert_observations(conn, batch)
            conn.commit()
        log.info(
            "reload-raw %s: 파일 %d개, 후보 %d행, %s %d행 (%s ~ %s, 도로 %s)",
            mode, files, len(batch), "넣을" if dry_run else "넣음", rows, start, end, sorted(roads),
        )
        return rows, files
    finally:
        if own_conn:
            conn.close()


def _iso_date(text: str) -> date:
    """CLI `--from`/`--to` 변환. YYYY-MM-DD가 아니면 argparse가 사용자에게 알린다."""
    try:
        return date.fromisoformat(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"YYYY-MM-DD 형식이어야 한다: {text}") from e


def main(argv: list[str] | None = None) -> int:
    """`purge --raw <gz> [--apply]` · `prune-raw [--apply]` · `reload-raw --from <날짜> --to <날짜> --road <도로> [--apply]`.

    기본은 dry-run으로 숫자만 출력한다.
    """
    parser = argparse.ArgumentParser(prog="python -m collector.maintenance", description="수집기 정비 도구")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("purge", help="저장 범위 밖 관측 행 정리")
    p.add_argument("--raw", type=Path, required=True, help="저장 범위 링크를 뽑을 ITS 원본 .xml.gz")
    p.add_argument("--apply", action="store_true", help="실제로 삭제하고 VACUUM한다(없으면 dry-run)")
    pr = sub.add_parser("prune-raw", help="오래된 원본 날짜 폴더 정리 (raw_keep_days)")
    pr.add_argument("--apply", action="store_true", help="실제로 삭제한다(없으면 dry-run)")
    rr = sub.add_parser("reload-raw", help="원본 gz에서 지정 도로 관측 재적재 (C-02 v2.2)")
    rr.add_argument("--from", dest="from_", type=_iso_date, required=True, metavar="YYYY-MM-DD", help="시작 날짜(포함)")
    rr.add_argument("--to", dest="to_", type=_iso_date, required=True, metavar="YYYY-MM-DD", help="끝 날짜(포함)")
    rr.add_argument("--road", dest="roads", action="append", required=True, help="넣을 도로(ITS roadName). 반복 지정 가능")
    rr.add_argument("--apply", action="store_true", help="실제로 넣는다(없으면 dry-run)")
    args = parser.parse_args(argv)

    from config.settings import get_settings

    settings = get_settings()

    if args.command == "prune-raw":
        files = prune_raw(now_kst(), settings, dry_run=not args.apply)
        print(f"{'적용' if args.apply else 'dry-run'}: 파일 {files}개")
        return 0

    if args.command == "reload-raw":
        print("주의: DB 백업은 자동이 아니다. --apply 전에 DB 파일을 수동으로 백업하라.")
        print("dry-run과 apply는 각각 범위 내 모든 파일을 파싱하므로 몇 분 걸릴 수 있다.")
        rows, files = _reload_raw(args.from_, args.to_, args.roads, settings=settings, dry_run=not args.apply)
        print(f"{'적용' if args.apply else 'dry-run'}: 파일 {files}개, {'넣은' if args.apply else '넣을'} 행 {rows}개")
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
