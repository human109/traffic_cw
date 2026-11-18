"""database.db 연결·스키마 테스트 (D-DAT-01)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from database.db import connect, init_db


def test_wal_and_fk(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.row_factory is sqlite3.Row
    finally:
        conn.close()


def test_readonly_rejects_write(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    conn = connect(db)
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
    conn = connect(db)
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

    conn = connect(tmp_path / "t.db")
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == get_settings().db_busy_timeout_ms
    finally:
        conn.close()


def test_init_idempotent(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
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
    conn = connect()
    try:
        init_db(conn)
    finally:
        conn.close()
    assert db.exists()
