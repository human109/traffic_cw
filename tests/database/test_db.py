"""database.db 연결·스키마 테스트 (D-DAT-01, Slice 1 M3)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from database.db import ROOT, connect, init_db


def test_wal_and_fk(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db", create=True)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.row_factory is sqlite3.Row
    finally:
        conn.close()


def test_readonly_rejects_write(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    conn = connect(db, create=True)
    init_db(conn)
    conn.close()

    ro = connect(db, readonly=True)
    try:
        assert ro.execute("SELECT COUNT(*) FROM road_segment").fetchone()[0] == 0
        with pytest.raises(sqlite3.OperationalError):
            ro.execute(
                "INSERT INTO road_segment (segment_id, road_name, start_node, end_node, direction, seq) "
                "VALUES ('X', 'r', 'a', 'b', 'd', 0)"
            )
    finally:
        ro.close()


def test_readonly_path_with_space_and_korean(tmp_path: Path) -> None:
    db = tmp_path / "공백 한글" / "t.db"
    conn = connect(db, create=True)
    init_db(conn)
    conn.execute(
        "INSERT INTO road_segment (segment_id, road_name, start_node, end_node, direction, seq) "
        "VALUES ('X', 'r', 'a', 'b', 'd', 0)"
    )
    conn.commit()
    conn.close()

    ro = connect(db, readonly=True)
    try:
        assert ro.execute("SELECT segment_id FROM road_segment").fetchone()[0] == "X"
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("DELETE FROM road_segment")
    finally:
        ro.close()


def test_busy_timeout_from_settings(tmp_path: Path) -> None:
    from config.settings import get_settings

    conn = connect(tmp_path / "t.db", create=True)
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == get_settings().db_busy_timeout_ms
    finally:
        conn.close()


def test_init_idempotent(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db", create=True)
    try:
        init_db(conn)
        init_db(conn)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "road_segment" in names and "segment_traffic_5min" in names
    finally:
        conn.close()


def test_connect_default_path_uses_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "sub" / "env.db"
    monkeypatch.setenv("DB_PATH", str(db))
    conn = connect(create=True)
    try:
        init_db(conn)
    finally:
        conn.close()
    assert db.exists()


def test_missing_db_raises_file_not_found(tmp_path: Path) -> None:
    # 쓰기 연결은 빈 DB를 몰래 만들지 않는다(M3). 새로 만드는 곳은 init_db.py뿐이다.
    db = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        connect(db)
    assert not db.exists()


def test_create_true_makes_file_and_parents(tmp_path: Path) -> None:
    db = tmp_path / "new" / "deep" / "t.db"
    conn = connect(db, create=True)
    try:
        assert db.exists()
    finally:
        conn.close()


def test_relative_path_resolved_at_repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 상대 경로는 실행 위치가 아니라 저장소 루트 기준으로 해석된다(M3).
    monkeypatch.chdir(tmp_path)  # 실행 위치와 무관함을 확인한다
    with pytest.raises(FileNotFoundError) as e:
        connect("no/such/x.db")
    resolved = ROOT / "no" / "such" / "x.db"
    assert str(resolved) in str(e.value)
    assert not resolved.exists()


def test_readonly_missing_db_still_operational_error(tmp_path: Path) -> None:
    # readonly 연결은 DB가 없으면 지금처럼 sqlite 오류를 낸다(만들지 않는다).
    with pytest.raises(sqlite3.OperationalError):
        connect(tmp_path / "none.db", readonly=True)


# --- C-01 v1.4 마이그레이션: model_evaluation.road_name (W-02) ---

# v1.3까지의 `model_evaluation` DDL(road_name 없음). 기존 운영 DB를 흉내 낸다.
_V13_MODEL_TABLES = """
CREATE TABLE model_registry (
    model_version   TEXT PRIMARY KEY,
    model_type      TEXT NOT NULL,
    target_var      TEXT NOT NULL,
    horizon         INTEGER NOT NULL,
    train_start     TEXT,
    train_end       TEXT,
    features        TEXT,
    hyperparams     TEXT,
    artifact_path   TEXT,
    trained_at      TEXT NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE model_evaluation (
    id              INTEGER PRIMARY KEY,
    model_version   TEXT NOT NULL REFERENCES model_registry(model_version),
    eval_type       TEXT NOT NULL,
    period_start    TEXT NOT NULL,
    period_end      TEXT NOT NULL,
    segment_id      TEXT,
    regime          TEXT,
    n_samples       INTEGER NOT NULL,
    mae             REAL,
    rmse            REAL,
    wape            REAL,
    grade_accuracy  REAL,
    evaluated_at    TEXT NOT NULL
);
"""


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _old_db_with_evaluations(tmp_path: Path, rows: list[tuple[str | None, str]]) -> sqlite3.Connection:
    """열이 없던 시절 스키마로 만든 DB에 평가 행을 넣어 돌려준다.

    `rows`는 (segment_id, regime) 쌍이다. 이 시절 대상 도로는 창원대로뿐이었다.
    """
    conn = connect(tmp_path / "old.db", create=True)
    conn.executescript(_V13_MODEL_TABLES)
    conn.execute(
        "INSERT INTO model_registry (model_version, model_type, target_var, horizon, trained_at)"
        " VALUES ('m1', 'recent_mean', 'speed', 5, '2026-11-20T10:00:00+09:00')"
    )
    conn.executemany(
        "INSERT INTO model_evaluation (model_version, eval_type, period_start, period_end,"
        " segment_id, regime, n_samples, evaluated_at)"
        " VALUES ('m1', 'live', '2026-11-19T00:00:00+09:00', '2026-11-19T23:59:59+09:00',"
        " ?, ?, 10, '2026-11-20T10:05:00+09:00')",
        rows,
    )
    conn.commit()
    return conn


def test_init_db_adds_road_name_and_labels_legacy_rows(tmp_path: Path) -> None:
    conn = _old_db_with_evaluations(tmp_path, [(None, "peak"), ("S1", "off_peak")])
    try:
        assert "road_name" not in _columns(conn, "model_evaluation")  # 구 스키마
        init_db(conn)
        assert "road_name" in _columns(conn, "model_evaluation")
        got = [r[0] for r in conn.execute("SELECT road_name FROM model_evaluation ORDER BY id")]
        assert got == ["창원대로", "창원대로"]  # v1.4 이전 행은 창원대로뿐이었다
        assert conn.execute("SELECT COUNT(*) FROM model_evaluation").fetchone()[0] == 2  # 행은 그대로
    finally:
        conn.close()


def test_init_db_migration_is_idempotent(tmp_path: Path) -> None:
    conn = _old_db_with_evaluations(tmp_path, [(None, "peak")])
    try:
        init_db(conn)
        init_db(conn)  # 두 번 실행해도 같다
        assert [r[0] for r in conn.execute("SELECT road_name FROM model_evaluation")] == ["창원대로"]
        assert conn.execute("SELECT COUNT(*) FROM model_evaluation").fetchone()[0] == 1
    finally:
        conn.close()


def test_init_db_migration_keeps_existing_road_names(tmp_path: Path) -> None:
    # 이미 도로가 채워진 행(신 스키마)은 마이그레이션이 덮어쓰지 않는다.
    conn = connect(tmp_path / "new.db", create=True)
    try:
        init_db(conn)
        conn.execute(
            "INSERT INTO model_registry (model_version, model_type, target_var, horizon, trained_at)"
            " VALUES ('m1', 'recent_mean', 'speed', 5, '2026-11-20T10:00:00+09:00')"
        )
        conn.execute(
            "INSERT INTO model_evaluation (model_version, eval_type, period_start, period_end,"
            " segment_id, regime, road_name, n_samples, evaluated_at)"
            " VALUES ('m1', 'live', '2026-11-19T00:00:00+09:00', '2026-11-19T23:59:59+09:00',"
            " NULL, 'peak', '원이대로', 10, '2026-11-20T10:05:00+09:00')"
        )
        conn.commit()
        init_db(conn)
        assert conn.execute("SELECT road_name FROM model_evaluation").fetchone()[0] == "원이대로"
    finally:
        conn.close()


def test_init_db_leaves_later_null_road_names_alone(tmp_path: Path) -> None:
    # 마이그레이션은 1회성이다. 열이 이미 있는 DB에서 나중에 생긴 NULL 행을 채우지 않는다
    # (모듈이 C-04대로 도로를 채워야 하고, 마이그레이션이 조용히 덮어쓰면 안 된다).
    conn = connect(tmp_path / "new.db", create=True)
    try:
        init_db(conn)  # 이 시점엔 행이 없어 채울 것도 없다
        conn.execute(
            "INSERT INTO model_registry (model_version, model_type, target_var, horizon, trained_at)"
            " VALUES ('m1', 'recent_mean', 'speed', 5, '2026-11-20T10:00:00+09:00')"
        )
        conn.execute(
            "INSERT INTO model_evaluation (model_version, eval_type, period_start, period_end,"
            " segment_id, regime, road_name, n_samples, evaluated_at)"
            " VALUES ('m1', 'live', '2026-11-19T00:00:00+09:00', '2026-11-19T23:59:59+09:00',"
            " NULL, 'peak', NULL, 10, '2026-11-20T10:05:00+09:00')"
        )
        conn.commit()
        init_db(conn)
        assert conn.execute("SELECT road_name FROM model_evaluation").fetchone()[0] is None
    finally:
        conn.close()


def test_init_db_migration_is_atomic_on_failure(tmp_path: Path) -> None:
    # ADD COLUMN과 UPDATE가 하나의 트랜잭션이다. UPDATE가 실패하면 열 추가도 되돌려진다.
    conn = _old_db_with_evaluations(tmp_path, [(None, "peak")])
    try:
        conn.execute(
            "CREATE TRIGGER block_update BEFORE UPDATE ON model_evaluation"
            " BEGIN SELECT RAISE(ABORT, 'test'); END;"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):  # 트리거 RAISE(ABORT)는 IntegrityError다
            init_db(conn)
        # ROLLBACK으로 열 추가도 되돌려진다(반쯤 적용된 마이그레이션이 남지 않는다).
        assert "road_name" not in _columns(conn, "model_evaluation")
        # 트리거를 지우면 다시 실행해 마이그레이션이 처음부터 끝까지 적용된다.
        conn.execute("DROP TRIGGER block_update")
        conn.commit()
        init_db(conn)
        assert "road_name" in _columns(conn, "model_evaluation")
        assert conn.execute("SELECT road_name FROM model_evaluation").fetchone()[0] == "창원대로"
    finally:
        conn.close()

