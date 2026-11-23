"""SQLite 연결·스키마 헬퍼 (C-06). 다른 모듈은 이 두 함수로만 DB에 연결한다."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from config.settings import get_settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
ROOT = Path(__file__).resolve().parents[1]  # 저장소 루트. 상대 db_path의 기준이다(M3).

# C-01 v1.4 마이그레이션이 v1.4 이전 `model_evaluation` 행에 채우는 도로. 그때까지 예측 대상은
# 창원대로뿐이었다. 설정값이 아니라 계약이 정한 역사적 사실이므로 하드코딩한다.
_LEGACY_ROAD_NAME = "창원대로"


def connect(path: str | Path | None = None, readonly: bool = False, create: bool = False) -> sqlite3.Connection:
    """SQLite 연결을 연다.

    - WAL 모드, `foreign_keys=ON`, `row_factory=sqlite3.Row`
    - `readonly=True`이면 `file:...?mode=ro` URI로 열어 쓰기가 `OperationalError`가 된다.
      (경로의 공백·한글은 `Path.as_uri()`가 퍼센트 인코딩한다.)
    - 상대 `path`는 실행 위치가 아니라 저장소 루트 기준으로 해석한다(C-06 v2).
    - `path=None`이면 `get_settings().db_path`를 쓴다.
    - 쓰기 연결에서 DB 파일이 없으면 빈 DB를 만들지 않고 `FileNotFoundError`를 낸다. 새로 만들
      수 있는 곳은 `scripts/init_db.py`뿐이고 그곳만 `create=True`를 넘긴다. `readonly` 연결은
      DB 파일이 없어도 지금처럼 sqlite가 `OperationalError`를 낸다.
    - 잠금 대기 시간은 `get_settings().db_busy_timeout_ms`.
    """
    settings = get_settings()
    db_path = Path(path) if path is not None else Path(settings.db_path)
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    busy_ms = settings.db_busy_timeout_ms
    if readonly:
        uri = db_path.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=busy_ms / 1000)
    else:
        if not db_path.exists():
            if not create:
                raise FileNotFoundError(f"DB 파일이 없다: {db_path} — scripts/init_db.py를 먼저 실행하라")
            db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=busy_ms / 1000)
        # journal_mode는 DB 파일에 기록되므로 쓰기 연결에서만 설정한다.
        conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={int(busy_ms)}")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """`database/schema.sql`을 실행하고 C-01 v1.4 마이그레이션을 적용한다. 재실행 안전하다.

    - `executescript`는 실행 전에 conn의 열린 트랜잭션을 먼저 암묵적으로 COMMIT한다. 따라서
      호출 전에 커밋하지 않은 변경이 있으면 그것도 확정된다. DDL 도중 오류가 나면 그때까지 실행된
      문장은 되돌려지지 않을 수 있다(스크립트 전체가 하나의 트랜잭션이 아님).
    - `CREATE TABLE IF NOT EXISTS`는 기존 테이블에 열을 더하지 않으므로, v1.4 마이그레이션
      (`_migrate_v14`)이 `model_evaluation.road_name`을 `ALTER TABLE ... ADD COLUMN`으로 더하고
      v1.4 이전 행(NULL)을 `'창원대로'`로 채운다. 열이 이미 있으면 아무것도 바꾸지 않는다.
    - 끝에서 `commit()`을 한 번 더 호출한다.
    """
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _migrate_v14(conn)
    conn.commit()


def _migrate_v14(conn: sqlite3.Connection) -> None:
    """C-01 v1.4: `model_evaluation.road_name` 추가와 v1.4 이전 행의 도로 채우기.

    1회성 마이그레이션이다. 열이 이미 있으면 아무것도 하지 않는다 — 나중에 생긴 `road_name`
    NULL 행을 조용히 `'창원대로'`로 바꾸지 않는다(C-04 v1.4대로 모듈이 도로를 채워야 한다).
    열을 더하는 경우에는 `BEGIN IMMEDIATE` … COMMIT로 ADD COLUMN과 UPDATE를 하나의 트랜잭션으로
    묶어 원자적으로 적용하고, 실패하면 ROLLBACK 후 예외를 다시 던진다.
    """
    if _has_column(conn, "model_evaluation", "road_name"):
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        # 잠금을 잡은 뒤 다시 확인한다(첫 확인과 BEGIN 사이에 다른 연결이 열을 더했을 수 있다).
        if not _has_column(conn, "model_evaluation", "road_name"):
            conn.execute("ALTER TABLE model_evaluation ADD COLUMN road_name TEXT")
            # v1.4 이전 평가는 모두 창원대로 것이었다(그때까지 대상 도로가 창원대로뿐).
            conn.execute(
                "UPDATE model_evaluation SET road_name = ? WHERE road_name IS NULL",
                (_LEGACY_ROAD_NAME,),
            )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))
