"""운영 DB 온라인 백업과 보관 정리 (SPEC 5.1, C-06 v2.2).

실행(저장소 루트): `python -m scripts.backup_db`

- `backup_dir`(기본 `data/backup`, 상대 경로는 저장소 루트 기준)에 `traffic_YYYYMMDD.db`
  (KST 날짜)로 sqlite backup API 온라인 백업한다. 운영 중(WAL 쓰기)에도 일관된 복사본이
  만들어지고, 같은 날 다시 실행하면 같은 파일을 덮어쓴다.
- 백업이 끝나면 `backup_keep_days`(기본 14일)보다 오래된 `traffic_YYYYMMDD.db` 파일만 지운다.
  이 패턴이 아닌 파일(사람이 둔 수동 백업 등)은 절대 지우지 않는다.
"""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

from common.logsetup import get_logger
from common.timeutil import KST, now_kst, require_aware
from config.settings import get_settings
from database.db import ROOT, connect

log = get_logger("scripts.backup_db")

# 보관 정리 대상 파일 이름. 이 패턴(정확히 `traffic_YYYYMMDD.db`)이 아닌 파일은 절대 지우지 않는다.
_BACKUP_NAME = re.compile(r"^traffic_(\d{8})\.db$")


def _backup_dir() -> Path:
    """`backup_dir`를 절대 경로로 돌려준다. 상대 경로는 저장소 루트 기준이다."""
    d = Path(get_settings().backup_dir)
    return d if d.is_absolute() else ROOT / d


def backup(now: datetime, conn: sqlite3.Connection | None = None) -> Path:
    """`backup_dir/traffic_YYYYMMDD.db`(KST 날짜)로 온라인 백업하고 파일 경로를 돌려준다 (C-06 v2.2).

    - sqlite backup API로 복사하므로 원본이 운영 중이어도 백업 시점의 일관된 내용을 담는다.
    - 먼저 `traffic_YYYYMMDD.db.tmp`에 백업한 뒤 성공하면 최종 이름으로 바꾼다(os.replace).
      백업이 실패하면 임시 파일을 지우고 예외를 다시 던지므로, 불완전한 파일이 최종 이름으로
      남거나 같은 날의 이전 백업이 손상되지 않는다.
    - 같은 날 다시 실행하면 같은 파일을 덮어써서 항상 최신 내용이 된다.
    - 백업이 끝나면 `backup_keep_days`보다 오래된 `traffic_YYYYMMDD.db`만 삭제한다.
    - `now`에 timezone 정보가 없으면 ValueError를 낸다(C-06). `conn=None`이면
      `database.db.connect()`로 연결하고 함수가 끝날 때 닫는다. 받은 `conn`은 닫지 않는다.
    - 이 함수는 DB 내용을 쓰지 않는다(백업 파일만 만든다).
    """
    require_aware(now)
    settings = get_settings()
    day = now.astimezone(KST).date()
    dest = _backup_dir() / f"traffic_{day:%Y%m%d}.db"
    dest.parent.mkdir(parents=True, exist_ok=True)
    own_conn = conn is None
    src = connect() if conn is None else conn
    # 먼저 임시 이름에 백업한 뒤 성공하면 최종 이름으로 바꾼다. 실패하면 불완전한 파일이
    # `traffic_YYYYMMDD.db` 이름으로 남아 보관 정리·대시보드에 진짜 백업처럼 보이는 일을 막는다.
    tmp = dest.with_name(dest.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
        os.replace(tmp, dest)
    except BaseException:
        if tmp.exists():
            tmp.unlink()
        raise
    finally:
        if own_conn:
            src.close()
    removed = prune_old_backups(dest.parent, day, settings.backup_keep_days)
    log.info("백업 완료: %s (오래된 백업 %d개 삭제)", dest, removed)
    return dest


def prune_old_backups(backup_dir: Path, today: date, keep_days: int) -> int:
    """`traffic_YYYYMMDD.db` 중 `keep_days`보다 오래된 파일만 지우고 개수를 돌려준다.

    `today - 파일 날짜 > keep_days`일 때만 삭제한다. 패턴이 맞지 않거나 날짜로 읽지 못하는
    파일은 건드리지 않는다.
    """
    removed = 0
    for p in sorted(backup_dir.iterdir()):
        if not p.is_file():
            continue
        m = _BACKUP_NAME.match(p.name)
        if m is None:
            continue
        try:
            file_day = datetime.strptime(m.group(1), "%Y%m%d").date()
        except ValueError:
            continue  # 날짜로 읽히지 않는 이름은 패턴에 맞는 백업이 아니다
        if (today - file_day).days > keep_days:
            p.unlink()
            removed += 1
            log.info("오래된 백업 삭제: %s", p.name)
    return removed


def main() -> int:
    """CLI: 지금(KST) 기준으로 백업하고 결과 경로를 출력한다."""
    p = backup(now_kst())
    print(f"백업 완료: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
