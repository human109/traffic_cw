"""scripts.load_segments 시드 적재 테스트 (D-DAT-01).

링크 CSV는 테스트 안에서 만드는 합성 값이다(synthetic). 실제 링크 ID가 아니다.
"""

from __future__ import annotations

import csv
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from common.timeutil import KST, to_iso
from config.segments import SEGMENTS
from database.db import connect, init_db
from scripts.load_segments import load

HEADER = "segment_id,seq,link_id,source,link_length_m,is_mainline,nodelink_ver,valid_from\n"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(tmp_path / "t.db", create=True)
    init_db(c)
    yield c
    c.close()


def _write_csv(path: Path, rows: list[str]) -> Path:
    path.write_text(HEADER + "".join(r + "\n" for r in rows), encoding="utf-8")
    return path


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_load_segments_idempotent(conn: sqlite3.Connection, tmp_path: Path) -> None:
    csv = _write_csv(
        tmp_path / "links.csv",
        [
            "S1,0,SYN0001,its,120.5,1,,2026-11-18T00:00:00+09:00",
            "S1,1,SYN0002,its,80,1,,2026-11-18T00:00:00+09:00",
        ],
    )
    n = len(SEGMENTS)
    assert load(conn, SEGMENTS, csv) == (n, 2)
    assert load(conn, SEGMENTS, csv) == (n, 2)
    assert _count(conn, "road_segment") == n
    assert _count(conn, "segment_link") == 2


def test_empty_links_csv_ok(conn: sqlite3.Connection, tmp_path: Path) -> None:
    csv = _write_csv(tmp_path / "links.csv", [])
    assert load(conn, SEGMENTS, csv) == (len(SEGMENTS), 0)
    assert _count(conn, "road_segment") == len(SEGMENTS)
    # 링크가 없으면 거리는 모른다 → NULL (0이 아님)
    assert conn.execute("SELECT COUNT(*) FROM road_segment WHERE distance_m IS NOT NULL").fetchone()[0] == 0


def test_load_real_links_csv(conn: sqlite3.Connection) -> None:
    """실제 `config/segment_links.csv`(표준노드링크 2026-11-11, R-03b)가 오류 없이 적재되는지 확인한다."""
    real_csv = Path(__file__).resolve().parents[2] / "config" / "segment_links.csv"
    with open(real_csv, encoding="utf-8-sig", newline="") as f:
        n_rows = sum(1 for _ in csv.DictReader(f))
    assert n_rows > 0
    assert load(conn, SEGMENTS, real_csv) == (len(SEGMENTS), n_rows)
    # UPSERT 키(source, link_id, valid_from)가 중복된 행이 있으면 여기서 드러난다
    assert _count(conn, "segment_link") == n_rows
    null_targets = conn.execute(
        "SELECT segment_id FROM road_segment WHERE is_target = 1 AND distance_m IS NULL"
    ).fetchall()
    assert [r[0] for r in null_targets] == []
    assert conn.execute("SELECT COUNT(*) FROM road_segment WHERE is_target = 1").fetchone()[0] > 0


def test_segment_fields(conn: sqlite3.Connection, tmp_path: Path) -> None:
    load(conn, SEGMENTS, _write_csv(tmp_path / "links.csv", []))
    s0 = conn.execute("SELECT * FROM road_segment WHERE segment_id='S0'").fetchone()
    s1 = conn.execute("SELECT * FROM road_segment WHERE segment_id='S1'").fetchone()
    assert s0["is_target"] == 0 and s1["is_target"] == 1
    assert s0["seq"] == 0 and s1["seq"] == 1
    assert s1["road_name"] == SEGMENTS[1]["road_name"]


def test_distance_sum_of_mainline(conn: sqlite3.Connection, tmp_path: Path) -> None:
    csv = _write_csv(
        tmp_path / "links.csv",
        [
            "S1,0,SYN0001,its,120.5,1,,2026-11-18T00:00:00+09:00",
            "S1,1,SYN0002,its,80,1,,2026-11-18T00:00:00+09:00",
            "S1,2,SYN0003,its,999,0,,2026-11-18T00:00:00+09:00",  # 비본선은 제외
        ],
    )
    load(conn, SEGMENTS, csv)
    d = conn.execute("SELECT distance_m FROM road_segment WHERE segment_id='S1'").fetchone()[0]
    assert d == pytest.approx(200.5)


def test_empty_length_is_null_and_distance_null(conn: sqlite3.Connection, tmp_path: Path) -> None:
    csv = _write_csv(
        tmp_path / "links.csv",
        [
            "S2,0,SYN0010,its,100,1,,2026-11-18T00:00:00+09:00",
            "S2,1,SYN0011,its,,1,,2026-11-18T00:00:00+09:00",
        ],
    )
    load(conn, SEGMENTS, csv)
    length = conn.execute("SELECT link_length_m, nodelink_ver FROM segment_link WHERE link_id='SYN0011'").fetchone()
    assert length["link_length_m"] is None
    assert length["nodelink_ver"] is None
    d = conn.execute("SELECT distance_m FROM road_segment WHERE segment_id='S2'").fetchone()[0]
    assert d is None


def test_upsert_updates_existing_link(conn: sqlite3.Connection, tmp_path: Path) -> None:
    load(conn, SEGMENTS, _write_csv(tmp_path / "a.csv", ["S3,0,SYN0020,its,,1,,2026-11-18T00:00:00+09:00"]))
    load(conn, SEGMENTS, _write_csv(tmp_path / "b.csv", ["S3,0,SYN0020,its,150,1,v1,2026-11-18T00:00:00+09:00"]))
    row = conn.execute("SELECT link_length_m, nodelink_ver FROM segment_link WHERE link_id='SYN0020'").fetchone()
    assert row["link_length_m"] == 150 and row["nodelink_ver"] == "v1"
    assert _count(conn, "segment_link") == 1
    d = conn.execute("SELECT distance_m FROM road_segment WHERE segment_id='S3'").fetchone()[0]
    assert d == pytest.approx(150)


@pytest.mark.parametrize("bad", ["2026-11-18", "2026-11-18T00:00:00", "18/11/2026", "not-a-time"])
def test_valid_from_without_offset_or_malformed_rejected(
    conn: sqlite3.Connection, tmp_path: Path, bad: str
) -> None:
    csv = _write_csv(tmp_path / "links.csv", [f"S1,0,SYN0001,its,100,1,,{bad}"])
    with pytest.raises(ValueError):
        load(conn, SEGMENTS, csv)
    assert _count(conn, "road_segment") == 0
    assert _count(conn, "segment_link") == 0


def test_valid_from_utc_converted_to_kst(conn: sqlite3.Connection, tmp_path: Path) -> None:
    csv = _write_csv(tmp_path / "links.csv", ["S1,0,SYN0001,its,100,1,,2026-11-18T00:00:00+00:00"])
    load(conn, SEGMENTS, csv)
    vf = conn.execute("SELECT valid_from FROM segment_link WHERE link_id='SYN0001'").fetchone()[0]
    assert vf == "2026-11-18T09:00:00+09:00"


def test_same_instant_different_notation_single_row(conn: sqlite3.Connection, tmp_path: Path) -> None:
    load(conn, SEGMENTS, _write_csv(tmp_path / "a.csv", ["S1,0,SYN0001,its,100,1,,2026-11-18T09:00:00+09:00"]))
    load(conn, SEGMENTS, _write_csv(tmp_path / "b.csv", ["S1,0,SYN0001,its,110,1,,2026-11-18T00:00:00+00:00"]))
    rows = conn.execute("SELECT valid_from, link_length_m FROM segment_link").fetchall()
    assert len(rows) == 1
    assert rows[0]["valid_from"] == "2026-11-18T09:00:00+09:00"
    assert rows[0]["link_length_m"] == 110


@pytest.mark.parametrize("bad", ["2", "-1", "yes", "1.0"])
def test_is_mainline_must_be_0_or_1(conn: sqlite3.Connection, tmp_path: Path, bad: str) -> None:
    csv = _write_csv(tmp_path / "links.csv", [f"S1,0,SYN0001,its,100,{bad},,2026-11-18T00:00:00+09:00"])
    with pytest.raises(ValueError):
        load(conn, SEGMENTS, csv)
    assert _count(conn, "road_segment") == 0
    assert _count(conn, "segment_link") == 0


def test_unknown_segment_id_fk_rollback(conn: sqlite3.Connection, tmp_path: Path) -> None:
    good = _write_csv(tmp_path / "a.csv", ["S1,0,SYN0001,its,100,1,,2026-11-18T00:00:00+09:00"])
    load(conn, SEGMENTS, good)
    before_seg = [tuple(r) for r in conn.execute("SELECT * FROM road_segment ORDER BY segment_id")]
    before_link = [tuple(r) for r in conn.execute("SELECT * FROM segment_link ORDER BY id")]

    bad = _write_csv(
        tmp_path / "b.csv",
        [
            "S1,0,SYN0001,its,999,1,,2026-11-18T00:00:00+09:00",  # 앞 행은 정상(갱신 시도)
            "S99,0,SYN0099,its,100,1,,2026-11-18T00:00:00+09:00",  # SEGMENTS에 없는 구간
        ],
    )
    changed = [dict(s, road_name="바뀐 이름") for s in SEGMENTS]
    with pytest.raises(sqlite3.IntegrityError):
        load(conn, changed, bad)

    assert [tuple(r) for r in conn.execute("SELECT * FROM road_segment ORDER BY segment_id")] == before_seg
    assert [tuple(r) for r in conn.execute("SELECT * FROM segment_link ORDER BY id")] == before_link


def test_missing_required_value_rejected(conn: sqlite3.Connection, tmp_path: Path) -> None:
    csv = _write_csv(tmp_path / "links.csv", ["S1,0,SYN0001,its,100,1,,"])  # valid_from 빈 값
    with pytest.raises(ValueError):
        load(conn, SEGMENTS, csv)
    assert _count(conn, "segment_link") == 0


def test_load_closes_links_absent_from_csv(conn: sqlite3.Connection, tmp_path: Path) -> None:
    # CSV에서 빠진 기존 유효 링크는 이번 적재 시각으로 valid_to를 닫는다(Slice 1 M4).
    csv1 = _write_csv(
        tmp_path / "a.csv",
        [
            "S1,0,SYN0001,its,100,1,,2026-11-18T00:00:00+09:00",
            "S1,1,SYN0002,its,100,1,,2026-11-18T00:00:00+09:00",
        ],
    )
    load(conn, SEGMENTS, csv1)
    csv2 = _write_csv(tmp_path / "b.csv", ["S1,0,SYN0001,its,100,1,,2026-11-18T00:00:00+09:00"])
    now = datetime(2026, 11, 19, 9, 0, tzinfo=KST)
    load(conn, SEGMENTS, csv2, now=now)
    rows = {r["link_id"]: r for r in conn.execute("SELECT * FROM segment_link")}
    assert rows["SYN0001"]["valid_to"] is None  # CSV에 있으므로 계속 유효
    assert rows["SYN0002"]["valid_to"] == "2026-11-19T09:00:00+09:00"
    # 닫힌 링크는 거리 합에서 빠진다
    d = conn.execute("SELECT distance_m FROM road_segment WHERE segment_id='S1'").fetchone()[0]
    assert d == pytest.approx(100)


def test_reload_same_csv_closes_nothing(conn: sqlite3.Connection, tmp_path: Path) -> None:
    csv = _write_csv(tmp_path / "a.csv", ["S1,0,SYN0001,its,100,1,,2026-11-18T00:00:00+09:00"])
    load(conn, SEGMENTS, csv)
    load(conn, SEGMENTS, csv)  # 같은 CSV를 다시 적재하면 아무것도 닫지 않는다
    assert all(r["valid_to"] is None for r in conn.execute("SELECT valid_to FROM segment_link"))


def test_closed_link_stays_closed(conn: sqlite3.Connection, tmp_path: Path) -> None:
    # 한 번 닫힌 링크는 뒤의 적재에서 valid_to를 다시 열지 않는다
    csv1 = _write_csv(
        tmp_path / "a.csv",
        ["S1,0,SYN0001,its,100,1,,2026-11-18T00:00:00+09:00"],
    )
    load(conn, SEGMENTS, csv1)
    load(conn, SEGMENTS, _write_csv(tmp_path / "b.csv", []), now=datetime(2026, 11, 19, 9, 0, tzinfo=KST))
    closed = conn.execute("SELECT valid_to FROM segment_link WHERE link_id='SYN0001'").fetchone()[0]
    assert closed == "2026-11-19T09:00:00+09:00"
    load(conn, SEGMENTS, csv1)  # 예전 버전을 다시 적재해도 이미 닫힌 행은 그대로다
    assert conn.execute("SELECT valid_to FROM segment_link WHERE link_id='SYN0001'").fetchone()[0] == closed
    assert _count(conn, "segment_link") == 1


def test_link_replacement_keeps_distance_and_valid_rows(conn: sqlite3.Connection, tmp_path: Path) -> None:
    # 링크 교체 시나리오: 한 링크 ID만 다른 ID로 바꾸고 길이는 같다.
    csv1 = _write_csv(
        tmp_path / "a.csv",
        [
            "S1,0,SYN0001,its,100,1,,2026-11-18T00:00:00+09:00",
            "S1,1,SYN0002,its,100,1,,2026-11-18T00:00:00+09:00",
        ],
    )
    load(conn, SEGMENTS, csv1)
    csv2 = _write_csv(
        tmp_path / "b.csv",
        [
            "S1,0,SYN0001,its,100,1,,2026-11-18T00:00:00+09:00",
            "S1,1,SYN0009,its,100,1,,2026-11-18T00:00:00+09:00",  # SYN0002 → SYN0009 교체
        ],
    )
    now = datetime(2026, 11, 19, 9, 0, tzinfo=KST)
    load(conn, SEGMENTS, csv2, now=now)
    rows = {r["link_id"]: r for r in conn.execute("SELECT * FROM segment_link")}
    assert rows["SYN0002"]["valid_to"] == to_iso(now)  # 옛 링크는 이번 적재 시각으로 닫힌다
    assert rows["SYN0009"]["valid_to"] is None  # 새 링크는 유효
    assert rows["SYN0001"]["valid_to"] is None  # 관계없는 링크는 그대로
    # 유효 행 수와 구간 거리는 변하지 않는다
    assert conn.execute("SELECT COUNT(*) FROM segment_link WHERE valid_to IS NULL").fetchone()[0] == 2
    d = conn.execute("SELECT distance_m FROM road_segment WHERE segment_id='S1'").fetchone()[0]
    assert d == pytest.approx(200)


# --- 원이대로 확장 시드 (C-01 v1.4, W-02) ---

REAL_LINKS_CSV = Path(__file__).resolve().parents[2] / "config" / "segment_links.csv"
W_SEGMENTS = ["W0", "W1", "W2", "W3", "W4", "W5"]


def test_real_seed_includes_wonidaero(conn: sqlite3.Connection) -> None:
    """`config` 시드가 창원대로 7 + 원이대로 6구간과 링크 74행을 적재한다(W-02)."""
    assert load(conn, SEGMENTS, REAL_LINKS_CSV) == (13, 74)
    assert _count(conn, "road_segment") == 13
    assert _count(conn, "segment_link") == 74
    assert conn.execute(
        "SELECT COUNT(*) FROM road_segment WHERE road_name = '원이대로'"
    ).fetchone()[0] == 6
    assert conn.execute(
        "SELECT COUNT(*) FROM segment_link l JOIN road_segment s USING (segment_id)"
        " WHERE s.road_name = '원이대로'"
    ).fetchone()[0] == 35


def test_real_seed_w_segments_are_reference_not_target(conn: sqlite3.Connection) -> None:
    # target_corridors=("창원대로",)인 동안 W는 is_target=0 → 성공률 분모·예측에 새지 않는다.
    load(conn, SEGMENTS, REAL_LINKS_CSV)
    assert conn.execute("SELECT SUM(is_target) FROM road_segment").fetchone()[0] == 6
    w_targets = conn.execute(
        "SELECT segment_id FROM road_segment WHERE road_name = '원이대로' AND is_target = 1"
    ).fetchall()
    assert [r[0] for r in w_targets] == []


def test_real_seed_w_segments_have_distance(conn: sqlite3.Connection) -> None:
    """W 구간 6개 모두 본선 링크 길이가 모두 있어 `distance_m`이 채워진다(링크 35행)."""
    load(conn, SEGMENTS, REAL_LINKS_CSV)
    rows = conn.execute(
        "SELECT segment_id, seq, distance_m FROM road_segment"
        " WHERE road_name = '원이대로' ORDER BY seq"
    ).fetchall()
    assert [r["segment_id"] for r in rows] == W_SEGMENTS
    for r in rows:
        assert r["distance_m"] is not None and r["distance_m"] > 0, r["segment_id"]
