"""`collector.maintenance` 테스트. 합성 DB(fixture_conn)와 테스트 안에서 만든 synthetic gzip XML만 쓴다."""

from __future__ import annotations

import gzip
import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from collector.maintenance import purge_outside_scope, store_scope_link_ids
from common.timeutil import KST
from config.settings import Settings

NOW = datetime(2026, 11, 19, 11, 0, tzinfo=KST)
SYN_ROAD = "합성도로"
SETTINGS = replace(Settings(), its_store_road_names=(SYN_ROAD,))

# 대상 링크(segment_link): SYN0000000~SYN0000005, 합성 DB에 이미 관측 행이 있다.
OUTSIDE = ["OTH0000001", "OTH0000002"]  # 범위 밖 도로
IN_SCOPE_NOT_TARGET = "INS0000001"  # 범위 안 도로지만 segment_link에 없음


def _raw(tmp_path: Path, roads: list[tuple[str, str]]) -> Path:
    """synthetic: (linkId, roadName) 목록으로 gzip ITS 원본을 만든다."""
    items = "".join(
        f"<item><roadName> {road} </roadName><linkId>{lid}</linkId><speed>50</speed>"
        "<createdDate>20261119100001</createdDate></item>"
        for lid, road in roads
    )
    xml = (
        "<response><header><resultCode>0</resultCode><resultMsg>SUCCESS</resultMsg></header>"
        f"<body><items>{items}</items></body></response>"
    )
    path = tmp_path / "100030.xml.gz"
    path.write_bytes(gzip.compress(xml.encode("utf-8")))
    return path


def _add_obs(conn: sqlite3.Connection, link_ids: list[str], n: int = 3) -> None:
    rows = [
        ("its", lid, f"2026-11-19T10:0{i}:01+09:00", f"2026-11-19T10:0{i}:30+09:00", 50.0)
        for lid in link_ids
        for i in range(n)
    ]
    conn.executemany(
        "INSERT INTO traffic_observation (source, link_id, source_timestamp, collected_at, speed) VALUES (?,?,?,?,?)",
        rows,
    )
    conn.execute(
        "INSERT INTO collection_log (source, started_at, status, links_received, record_count)"
        " VALUES ('its', '2026-11-19T10:00:30+09:00', 'success', 0, 0)"
    )
    conn.commit()


def _links(conn: sqlite3.Connection) -> dict[str, int]:
    return {r[0]: r[1] for r in conn.execute("SELECT link_id, COUNT(*) FROM traffic_observation GROUP BY link_id")}


def test_store_scope_link_ids(tmp_path: Path) -> None:
    raw = _raw(tmp_path, [("SYN0000001", SYN_ROAD), (IN_SCOPE_NOT_TARGET, SYN_ROAD), ("OTH0000001", "다른도로")])
    assert store_scope_link_ids(raw, SETTINGS) == {"SYN0000001", IN_SCOPE_NOT_TARGET}


def test_purge_apply(fixture_conn: sqlite3.Connection, tmp_path: Path) -> None:
    _add_obs(fixture_conn, OUTSIDE + [IN_SCOPE_NOT_TARGET])
    before = _links(fixture_conn)
    raw = _raw(tmp_path, [("SYN0000001", SYN_ROAD), (IN_SCOPE_NOT_TARGET, SYN_ROAD)] + [(x, "다른도로") for x in OUTSIDE])
    keep_ids = store_scope_link_ids(raw, SETTINGS)

    stats = purge_outside_scope(fixture_conn, keep_ids, dry_run=False, now=NOW)

    after = _links(fixture_conn)
    assert set(after) == set(before) - set(OUTSIDE)
    # 대상 링크(SYN0000000 등)는 keep 집합에 없어도 남는다
    assert "SYN0000000" in after and "SYN0000000" not in keep_ids
    assert after == {k: v for k, v in before.items() if k not in OUTSIDE}
    total = sum(before.values())
    assert stats == {"total": total, "keep": total - 6, "delete": 6, "keep_links": len(before) - 2}
    assert fixture_conn.execute("SELECT COUNT(*) FROM collection_log").fetchone()[0] == 1  # 다른 테이블 그대로
    assert fixture_conn.execute("SELECT COUNT(*) FROM segment_link").fetchone()[0] == 6


def test_purge_dry_run_deletes_nothing(fixture_conn: sqlite3.Connection) -> None:
    _add_obs(fixture_conn, OUTSIDE)
    before = _links(fixture_conn)
    stats = purge_outside_scope(fixture_conn, {"SYN0000001"}, now=NOW)  # 기본 dry_run
    assert stats["delete"] == 6
    assert _links(fixture_conn) == before


def test_empty_keep_rejected(fixture_conn: sqlite3.Connection) -> None:
    _add_obs(fixture_conn, OUTSIDE)
    before = _links(fixture_conn)
    with pytest.raises(ValueError):
        purge_outside_scope(fixture_conn, set(), dry_run=False, now=NOW)
    assert _links(fixture_conn) == before


def test_expired_link_not_protected(fixture_conn: sqlite3.Connection) -> None:
    # valid_to가 지난 링크는 대상이 아니므로 keep 집합에 없으면 지워진다.
    fixture_conn.execute("UPDATE segment_link SET valid_to='2026-06-01T00:00:00+09:00' WHERE link_id='SYN0000000'")
    fixture_conn.commit()
    purge_outside_scope(fixture_conn, {"SYN0000001"}, dry_run=False, now=NOW)
    assert "SYN0000000" not in _links(fixture_conn)


def test_failure_rolls_back(fixture_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    _add_obs(fixture_conn, OUTSIDE)
    before = _links(fixture_conn)
    real_execute = fixture_conn.execute

    class _Conn:
        """DELETE FROM traffic_observation 직후에 실패하는 연결 대역."""

        def __getattr__(self, name: str) -> object:
            return getattr(fixture_conn, name)

        def execute(self, sql: str, *args: object) -> object:
            cur = real_execute(sql, *args)
            if sql.startswith("DELETE FROM traffic_observation"):
                raise sqlite3.OperationalError("synthetic failure")
            return cur

    with pytest.raises(sqlite3.OperationalError):
        purge_outside_scope(_Conn(), {"SYN0000001"}, dry_run=False, now=NOW)  # type: ignore[arg-type]
    assert _links(fixture_conn) == before


def test_naive_now_rejected(fixture_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        purge_outside_scope(fixture_conn, {"SYN0000001"}, now=datetime(2026, 11, 19, 11, 0))
