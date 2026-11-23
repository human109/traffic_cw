"""`scripts/init_db.py` 전체 경로 테스트 (W-02).

운영 DB(`data/traffic.db`)는 쓰지 않는다 — `DB_PATH`를 tmp로 돌려 새 DB를 만든다.
적재 결과는 `config.segments.SEGMENTS`·`config/segment_links.csv`(창원대로 7 + 원이대로 6구간,
링크 74행)와 같아야 한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from database.db import connect
from scripts import init_db

W_SEGMENTS = ["W0", "W1", "W2", "W3", "W4", "W5"]


def test_init_db_script_loads_both_roads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "init.db"
    monkeypatch.setenv("DB_PATH", str(db))

    assert init_db.main() == 0

    conn = connect(db, readonly=True)
    try:
        assert conn.execute("SELECT COUNT(*) FROM road_segment").fetchone()[0] == 13
        assert conn.execute("SELECT COUNT(*) FROM segment_link").fetchone()[0] == 74
        assert conn.execute("SELECT SUM(is_target) FROM road_segment").fetchone()[0] == 6
        w = conn.execute(
            "SELECT segment_id, distance_m FROM road_segment"
            " WHERE road_name = '원이대로' ORDER BY seq"
        ).fetchall()
        assert [r[0] for r in w] == W_SEGMENTS
        assert all(r[1] is not None and r[1] > 0 for r in w)  # W 거리가 채워졌다
        # 마이그레이션과 무관하게 model_evaluation.road_name 열이 있는 새 DB다 (C-01 v1.4).
        cols = {r[1] for r in conn.execute("PRAGMA table_info(model_evaluation)")}
        assert "road_name" in cols
        assert conn.execute("SELECT COUNT(*) FROM calendar_info").fetchone()[0] > 0
    finally:
        conn.close()


def test_init_db_script_rerunnable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "init.db"))
    assert init_db.main() == 0
    assert init_db.main() == 0  # 두 번 실행해도 결과가 같다(멱등)
    conn = connect(tmp_path / "init.db", readonly=True)
    try:
        assert conn.execute("SELECT COUNT(*) FROM road_segment").fetchone()[0] == 13
        assert conn.execute("SELECT COUNT(*) FROM segment_link").fetchone()[0] == 74
    finally:
        conn.close()
