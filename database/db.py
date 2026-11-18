"""SQLite 연결·스키마 헬퍼 (C-06). 다른 모듈은 이 두 함수로만 DB에 연결한다."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from config.settings import get_settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(path: str | Path | None = None, readonly: bool = False) -> sqlite3.Connection:
    """SQLite 연결을 연다.

    - WAL 모드, `foreign_keys=ON`, `row_factory=sqlite3.Row`
    - `readonly=True`이면 `file:...?mode=ro` URI로 열어 쓰기가 `OperationalError`가 된다.
      (경로의 공백·한글은 `Path.as_uri()`가 퍼센트 인코딩한다.)
    - `path=None`이면 `get_settings().db_path`를 쓴다.
    - 잠금 대기 시간은 `get_settings().db_busy_timeout_ms`.
    """
    settings = get_settings()
    db_path = Path(path) if path is not None else Path(settings.db_path)
    busy_ms = settings.db_busy_timeout_ms
    if readonly:
        uri = db_path.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=busy_ms / 1000)
    else:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=busy_ms / 1000)
        # journal_mode는 DB 파일에 기록되므로 쓰기 연결에서만 설정한다.
        conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={int(busy_ms)}")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """`database/schema.sql`을 실행한다. 모든 DDL이 `IF NOT EXISTS`라 다시 실행해도 안전하다.

    트랜잭션 동작: `executescript`는 실행 전에 conn의 열린 트랜잭션을 먼저 암묵적으로 COMMIT한다.
    따라서 호출 전에 커밋하지 않은 변경이 있으면 그것도 확정된다. DDL 도중 오류가 나면
    그때까지 실행된 문장은 되돌려지지 않을 수 있다(스크립트 전체가 하나의 트랜잭션이 아님).
    끝에서 `commit()`을 한 번 더 호출한다.
    """
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
