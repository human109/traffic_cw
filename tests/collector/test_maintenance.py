"""`collector.maintenance` 테스트. 합성 DB(fixture_conn)와 테스트 안에서 만든 synthetic gzip XML만 쓴다."""

from __future__ import annotations

import gzip
import shutil
import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from collector import maintenance
from collector.maintenance import prune_raw, purge_outside_scope, store_scope_link_ids
from common.timeutil import KST
from config.settings import Settings

NOW = datetime(2026, 11, 19, 11, 0, tzinfo=KST)
PRUNE_NOW = datetime(2026, 11, 20, 3, 0, tzinfo=KST)
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


def test_purge_cli_dry_run_then_apply(
    tmp_path: Path, fixture_db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """D-COL-07 B5: CLI는 기본 dry-run(무삭제)이고 --apply면 삭제+VACUUM한다."""
    conn = sqlite3.connect(fixture_db)
    _add_obs(conn, OUTSIDE + [IN_SCOPE_NOT_TARGET])
    conn.close()
    raw = _raw(tmp_path, [("SYN0000001", SYN_ROAD), (IN_SCOPE_NOT_TARGET, SYN_ROAD)] + [(x, "다른도로") for x in OUTSIDE])
    monkeypatch.setattr("config.settings.get_settings", lambda: SETTINGS)

    def fake_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        return sqlite3.connect(fixture_db)

    monkeypatch.setattr("database.db.connect", fake_connect)  # 운영 DB 대신 합성 DB

    assert maintenance.main(["purge", "--raw", str(raw)]) == 0  # 기본 dry-run
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "백업은 자동이 아니다" in out  # 안전 문구는 항상 출력 (B6)
    assert "대상 DB" not in out  # --apply일 때만 DB 경로 출력
    c = sqlite3.connect(fixture_db)
    before = c.execute("SELECT COUNT(*) FROM traffic_observation").fetchone()[0]
    c.close()

    assert maintenance.main(["purge", "--raw", str(raw), "--apply"]) == 0
    out = capsys.readouterr().out
    assert "적용" in out and "VACUUM 완료" in out
    assert "대상 DB" in out  # --apply 시 해석된 DB 절대 경로 (B6)
    c = sqlite3.connect(fixture_db)
    after = c.execute("SELECT COUNT(*) FROM traffic_observation").fetchone()[0]
    ids = {r[0] for r in c.execute("SELECT DISTINCT link_id FROM traffic_observation")}
    c.close()
    assert after < before
    assert not (set(OUTSIDE) & ids)  # 범위 밖 행은 지워졌다
    assert IN_SCOPE_NOT_TARGET in ids  # 범위 안 행은 남는다


def test_purge_deleted_count_mismatch_rolls_back(fixture_conn: sqlite3.Connection) -> None:
    """D-COL-07 B7: DELETE rowcount가 예상과 다르면 RuntimeError로 rollback한다."""
    _add_obs(fixture_conn, OUTSIDE)
    before = _links(fixture_conn)

    class _WrongCountConn:
        """DELETE rowcount를 실제보다 1 크게 보고하는 연결 대역."""

        def __init__(self, real: sqlite3.Connection) -> None:
            self._real = real

        def __getattr__(self, name: str) -> object:
            return getattr(self._real, name)

        def execute(self, sql: str, *args: object) -> object:
            cur = self._real.execute(sql, *args)
            if sql.startswith("DELETE FROM traffic_observation"):
                expected = cur.rowcount + 1

                class _WrongCountCursor:
                    rowcount = expected

                    def fetchone(self) -> object:
                        return cur.fetchone()

                return _WrongCountCursor()
            return cur

    with pytest.raises(RuntimeError, match="삭제 행 수가 예상과 다르다"):
        purge_outside_scope(_WrongCountConn(fixture_conn), {"SYN0000001"}, dry_run=False, now=NOW)  # type: ignore[arg-type]
    assert _links(fixture_conn) == before  # rollback됐다


def test_purge_drop_failure_does_not_mask_original_error(
    fixture_conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    """D-COL-07 B7: finally의 임시 테이블 DROP 실패가 원래 예외를 가리지 않는다."""
    _add_obs(fixture_conn, OUTSIDE)
    before = _links(fixture_conn)
    real_execute = fixture_conn.execute

    class _BrokenDropConn:
        """DELETE 직후와 임시 테이블 DROP에서 실패하는 연결 대역."""

        def __getattr__(self, name: str) -> object:
            return getattr(fixture_conn, name)

        def execute(self, sql: str, *args: object) -> object:
            if sql.startswith("DROP TABLE"):
                raise sqlite3.OperationalError("synthetic drop failure")
            if sql.startswith("DELETE FROM traffic_observation"):
                raise sqlite3.OperationalError("synthetic delete failure")
            return real_execute(sql, *args)

    with pytest.raises(sqlite3.OperationalError, match="synthetic delete failure"):
        purge_outside_scope(_BrokenDropConn(), {"SYN0000001"}, dry_run=False, now=NOW)  # type: ignore[arg-type]
    assert "임시 테이블 정리 실패" in caplog.text  # DROP 실패는 경고일 뿐이다
    assert _links(fixture_conn) == before  # rollback됐다


# --- prune_raw (D-COL-06) ---


def _prune_settings(tmp_path: Path, keep_days: int) -> Settings:
    return replace(Settings(), raw_dir=str(tmp_path / "raw"), raw_keep_days=keep_days)


def _make_raw(raw_dir: Path, sources: dict[str, dict[str, int]]) -> Path:
    """synthetic: {source: {폴더이름: 파일 수}} 구조로 raw 디렉터리를 만든다."""
    for source, sub in sources.items():
        for name, n_files in sub.items():
            d = raw_dir / source / name
            d.mkdir(parents=True, exist_ok=True)
            for i in range(n_files):
                (d / f"{i:06d}.xml.gz").write_bytes(b"<x/>")
    return raw_dir


def test_prune_raw_deletes_only_older_than_keep_days(tmp_path: Path) -> None:
    raw = _make_raw(
        tmp_path / "raw",
        {"its": {"20261020": 2, "20261021": 1, "20261110": 3}, "other": {"20261001": 4}},
    )
    # keep_days=30, now=2026-11-20 → 기준일 2026-10-21. "이전"만 삭제 (경계일 20261021은 보존).
    n = prune_raw(PRUNE_NOW, _prune_settings(tmp_path, 30), dry_run=False)
    assert n == 2 + 4  # 20261020(2개) + other/20261001(4개)
    assert not (raw / "its" / "20261020").exists()
    assert not (raw / "other" / "20261001").exists()
    assert (raw / "its" / "20261021").is_dir()  # 기준일 당일은 보존
    assert (raw / "its" / "20261110").is_dir()


def test_prune_raw_keeps_non_date_folders(tmp_path: Path) -> None:
    raw = _make_raw(
        tmp_path / "raw",
        {"its": {"notadate": 1, "20261399": 1, "2026101": 1, "20260101": 2}},
    )
    (raw / "its" / "loose.xml.gz").write_bytes(b"<x/>")  # 날짜 폴더 밖 파일
    n = prune_raw(PRUNE_NOW, _prune_settings(tmp_path, 30), dry_run=False)
    assert n == 2  # 20260101만 대상
    for name in ("notadate", "20261399", "2026101"):
        assert (raw / "its" / name).is_dir()  # 8자리 날짜가 아니거나 실제 날짜가 아니면 건드리지 않는다
    assert (raw / "its" / "loose.xml.gz").exists()


def test_prune_raw_always_keeps_today_and_yesterday(tmp_path: Path) -> None:
    raw = _make_raw(
        tmp_path / "raw",
        {"its": {"20261120": 1, "20261119": 1, "20261118": 1}},
    )
    # keep_days=0이면 기준일이 오늘이지만, 오늘·어제는 설정과 무관하게 보존한다(안전장치).
    n = prune_raw(PRUNE_NOW, _prune_settings(tmp_path, 0), dry_run=False)
    assert n == 1  # 20261118(그저께)만 삭제
    assert (raw / "its" / "20261120").is_dir()
    assert (raw / "its" / "20261119").is_dir()
    assert not (raw / "its" / "20261118").exists()


def test_prune_raw_dry_run_deletes_nothing(tmp_path: Path) -> None:
    raw = _make_raw(tmp_path / "raw", {"its": {"20260101": 3, "20261110": 1}})
    n = prune_raw(PRUNE_NOW, _prune_settings(tmp_path, 30))  # 기본 dry-run
    assert n == 3  # 지울 파일 수만 센다
    assert (raw / "its" / "20260101").is_dir()
    assert len(list((raw / "its" / "20260101").iterdir())) == 3


def test_prune_raw_missing_dir_returns_zero(tmp_path: Path) -> None:
    assert prune_raw(PRUNE_NOW, _prune_settings(tmp_path, 30)) == 0


def test_prune_raw_naive_now_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        prune_raw(datetime(2026, 11, 20, 3, 0), _prune_settings(tmp_path, 30))


@pytest.mark.parametrize("empty", ["", "   ", "\t "], ids=["empty", "spaces", "tabs"])
def test_prune_raw_empty_raw_dir_rejected(tmp_path: Path, empty: str) -> None:
    """D-COL-07 A1: raw_dir이 빈 문자열·공백이면 ValueError. 아무것도 지우지 않는다."""
    with pytest.raises(ValueError):
        prune_raw(PRUNE_NOW, replace(_prune_settings(tmp_path, 30), raw_dir=empty))


def test_prune_raw_resolves_relative_raw_dir_to_repo_root() -> None:
    """D-COL-07 A2: 상대 raw_dir은 저장소 루트 기준으로 해석된다. 경로 계산만 검사한다."""
    from collector.paths import ROOT, resolve_path

    assert resolve_path("data/raw") == ROOT / "data" / "raw"
    assert resolve_path(ROOT / "data" / "raw") == ROOT / "data" / "raw"  # 절대 경로는 그대로


def test_prune_raw_continues_when_one_folder_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """D-COL-07 A3: 한 폴더 삭제가 실패해도 나머지를 계속 지운다. 실패 파일은 반환값에 세지 않는다."""
    raw = _make_raw(tmp_path / "raw", {"its": {"20260101": 2, "20260201": 1, "20261110": 1}})
    real_rmtree = shutil.rmtree

    def flaky_rmtree(path: object, *args: object, **kwargs: object) -> None:
        if Path(str(path)).name == "20260101":
            raise OSError("synthetic rmtree failure")
        real_rmtree(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(maintenance.shutil, "rmtree", flaky_rmtree)
    n = prune_raw(PRUNE_NOW, _prune_settings(tmp_path, 30), dry_run=False)
    assert n == 1  # 성공한 폴더(20260201)의 파일 수만 센다
    assert (raw / "its" / "20260101").is_dir()  # 실패한 폴더는 남는다
    assert not (raw / "its" / "20260201").exists()  # 나머지는 계속 지운다
    assert (raw / "its" / "20261110").is_dir()  # 보존 대상
    assert "synthetic rmtree failure" in caplog.text  # 실패는 경고 로그로 남는다


def test_prune_raw_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    raw = _make_raw(tmp_path / "raw", {"its": {"20260101": 2, "20261110": 1}})
    monkeypatch.setattr("config.settings.get_settings", lambda: _prune_settings(tmp_path, 30))
    monkeypatch.setattr(maintenance, "now_kst", lambda: PRUNE_NOW)  # CLI는 내부에서 now_kst()를 쓴다

    assert maintenance.main(["prune-raw"]) == 0  # 기본 dry-run
    assert "2" in capsys.readouterr().out
    assert (raw / "its" / "20260101").is_dir()

    assert maintenance.main(["prune-raw", "--apply"]) == 0
    assert not (raw / "its" / "20260101").exists()
    assert (raw / "its" / "20261110").is_dir()
