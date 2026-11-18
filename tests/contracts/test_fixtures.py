import sqlite3

from tests.conftest import FIXTURE_DIR


def test_fixture_marked_synthetic(fixture_conn: sqlite3.Connection) -> None:
    sources = {r[0] for r in fixture_conn.execute("SELECT DISTINCT source FROM traffic_observation")}
    link_sources = {r[0] for r in fixture_conn.execute("SELECT DISTINCT source FROM segment_link")}
    assert sources == {"synthetic"}
    assert link_sources == {"synthetic"}
    for name in ("its_sample_synthetic.xml", "its_sample_partial_synthetic.xml"):
        first_line = (FIXTURE_DIR / name).read_text(encoding="utf-8").splitlines()[0]
        assert "synthetic" in first_line


def test_fixture_gap_and_flags(fixture_conn: sqlite3.Connection) -> None:
    gap = fixture_conn.execute(
        "SELECT COUNT(*) FROM traffic_observation WHERE link_id='SYN0000003'"
        " AND source_timestamp BETWEEN '2026-11-16T07:20:00+09:00' AND '2026-11-16T07:40:00+09:00'"
    ).fetchone()[0]
    assert gap == 0
    flagged = fixture_conn.execute(
        "SELECT link_id, source_timestamp, speed, quality_flag FROM traffic_observation"
        " WHERE quality_flag != 'ok' ORDER BY link_id"
    ).fetchall()
    assert [tuple(r) for r in flagged] == [
        ("SYN0000002", "2026-11-16T07:10:00+09:00", 0.0, "default_value"),
        ("SYN0000004", "2026-11-16T07:15:00+09:00", 200.0, "out_of_range"),
    ]


def test_fixture_timestamps_kst(fixture_conn: sqlite3.Connection) -> None:
    bad = fixture_conn.execute(
        "SELECT COUNT(*) FROM traffic_observation WHERE source_timestamp NOT LIKE '%+09:00'"
        " OR collected_at NOT LIKE '%+09:00'"
    ).fetchone()[0]
    assert bad == 0
