import re
import sqlite3
from pathlib import Path

from tests.fixtures.synthetic_db import CONTRACT_DDL, ROOT

EXPECTED_TABLES = {
    "road_segment",
    "segment_link",
    "traffic_observation",
    "segment_traffic_5min",
    "traffic_prediction",
    "model_registry",
    "model_evaluation",
    "collection_log",
    "calendar_info",
    "publish_log",
}


def _normalize(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", "", sql)
    return re.sub(r"\s+", " ", sql).strip()


def test_schema_matches_contract() -> None:
    impl = ROOT / "database" / "schema.sql"
    assert impl.exists(), "database/schema.sql 이 없다 (D-DAT-01)"
    assert _normalize(impl.read_text(encoding="utf-8")) == _normalize(CONTRACT_DDL.read_text(encoding="utf-8"))


def test_tables_exist(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "c.db")
    conn.executescript(CONTRACT_DDL.read_text(encoding="utf-8"))
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert names == EXPECTED_TABLES


def test_contract_ddl_rerunnable(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "c.db")
    ddl = CONTRACT_DDL.read_text(encoding="utf-8")
    conn.executescript(ddl)
    conn.executescript(ddl)
    conn.close()
