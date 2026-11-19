"""scripts.backup_db 백업·보관 정리 테스트 (D-DAT-05, SPEC 5.1).

운영 DB(`data/traffic.db`)와 운영 백업 디렉터리(`data/backup`)는 절대 쓰지 않는다.
`backup_dir`·`backup_keep_days`는 임시 경로로 갈아끼운 Settings를 사용한다.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest

from common.timeutil import KST, now_kst
from config.settings import Settings
from database.db import connect, init_db
from scripts import backup_db

NOW = datetime(2026, 11, 20, 3, 5, tzinfo=KST)  # 금요일 새벽 (운영 백업 예정 시각)


class _FailingSource:
    """`backup()` 도중 예외를 던지는 원본 대역(테스트 코드 안에서만 쓴다)."""

    def __init__(self, inner: sqlite3.Connection) -> None:
        self._inner = inner

    def backup(self, target: sqlite3.Connection) -> None:
        raise RuntimeError("백업 실패 테스트")

    def close(self) -> None:
        self._inner.close()

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    s = Settings(backup_dir=str(tmp_path / "backup"), backup_keep_days=14)
    monkeypatch.setattr(backup_db, "get_settings", lambda: s)
    return s


@pytest.fixture
def src(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(tmp_path / "src.db", create=True)
    init_db(c)
    yield c
    c.close()


def _add_segment(conn: sqlite3.Connection, segment_id: str) -> None:
    conn.execute(
        "INSERT INTO road_segment (segment_id, road_name, start_node, end_node, direction, seq)"
        " VALUES (?, '합성도로', '합성A', '합성B', '합성방향', 0)",
        (segment_id,),
    )
    conn.commit()


def test_backup_creates_file_with_same_content(
    settings: Settings, src: sqlite3.Connection
) -> None:
    _add_segment(src, "S1")
    p = backup_db.backup(NOW, conn=src)
    assert p == Path(settings.backup_dir) / "traffic_20261120.db"
    assert p.exists()
    chk = sqlite3.connect(p)
    try:
        tables = {r[0] for r in chk.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"road_segment", "segment_traffic_5min", "calendar_info"} <= tables
        assert chk.execute("SELECT segment_id FROM road_segment").fetchone()[0] == "S1"
    finally:
        chk.close()


def test_filename_uses_kst_date(settings: Settings, src: sqlite3.Connection) -> None:
    # 2026-11-19 18:05 UTC = 2026-11-20 03:05 KST → 파일 이름은 KST 날짜다.
    p = backup_db.backup(datetime(2026, 11, 19, 18, 5, tzinfo=timezone.utc), conn=src)
    assert p.name == "traffic_20261120.db"


def test_same_day_rerun_overwrites(settings: Settings, src: sqlite3.Connection) -> None:
    d = Path(settings.backup_dir)
    _add_segment(src, "S1")
    first = backup_db.backup(NOW, conn=src)
    _add_segment(src, "S2")  # 재실행 사이에 원본이 늘었다
    second = backup_db.backup(NOW, conn=src)
    assert first == second
    assert [f.name for f in d.iterdir()] == ["traffic_20261120.db"]  # 파일이 하나다
    chk = sqlite3.connect(second)
    try:
        assert chk.execute("SELECT COUNT(*) FROM road_segment").fetchone()[0] == 2  # 최신 내용
    finally:
        chk.close()


def test_prunes_only_older_than_keep_days(
    settings: Settings, src: sqlite3.Connection
) -> None:
    d = Path(settings.backup_dir)
    d.mkdir(parents=True)
    # 14일 초과만 삭제: 15일 전은 지우고, 14일·13일 전은 남긴다.
    (d / "traffic_20261105.db").write_bytes(b"old")   # 15일 전
    (d / "traffic_20261106.db").write_bytes(b"edge")  # 정확히 14일 전
    (d / "traffic_20261107.db").write_bytes(b"ok")    # 13일 전
    backup_db.backup(NOW, conn=src)
    assert not (d / "traffic_20261105.db").exists()
    assert (d / "traffic_20261106.db").exists()
    assert (d / "traffic_20261107.db").exists()
    assert (d / "traffic_20261120.db").exists()


def test_never_deletes_files_outside_pattern(
    settings: Settings, src: sqlite3.Connection
) -> None:
    d = Path(settings.backup_dir)
    d.mkdir(parents=True)
    kept = [
        d / "manual_backup_20260101.db",  # 사람이 둔 수동 백업
        d / "traffic_2026010.db",         # 자릿수가 맞지 않다
        d / "traffic_20261301.db",        # 날짜로 읽히지 않는다(13월)
        d / "traffic_20260101.db.bak",    # 확장자가 다르다
        d / "traffic_20200101.db-wal",    # 사이드카 형태 이름
        d / "readme.txt",
        d / "sub",                        # 디렉터리
    ]
    kept[-1].mkdir()
    for f in kept[:-1]:
        f.write_text("x")
    (d / "traffic_20200101.db").write_text("x")  # 패턴에 맞고 아주 오래된 것만 삭제된다
    backup_db.backup(NOW, conn=src)
    for f in kept:
        assert f.exists(), f"{f} 는 보존되어야 한다"
    assert not (d / "traffic_20200101.db").exists()


def test_naive_now_raises(src: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        backup_db.backup(datetime(2026, 11, 20, 3, 5), conn=src)  # timezone 없음 (C-06)


def test_failed_backup_leaves_no_final_or_tmp_file(settings: Settings) -> None:
    # 이전 백업이 없을 때 실패하면 최종 이름·임시 이름 모두 아무것도 남지 않는다.
    with pytest.raises(RuntimeError):
        backup_db.backup(NOW, conn=_FailingSource(sqlite3.connect(":memory:")))
    d = Path(settings.backup_dir)
    assert d.exists()
    assert list(d.iterdir()) == []


def test_failed_backup_preserves_previous_same_day_backup(
    settings: Settings, src: sqlite3.Connection
) -> None:
    d = Path(settings.backup_dir)
    _add_segment(src, "S1")
    p = backup_db.backup(NOW, conn=src)
    before = p.read_bytes()
    _add_segment(src, "S2")  # 원본이 늘어도 실패하면 이전 백업이 남아 있어야 한다

    with pytest.raises(RuntimeError):
        backup_db.backup(NOW, conn=_FailingSource(src))

    assert p.read_bytes() == before  # 같은 날 이전 백업이 그대로다
    assert {f.name for f in d.iterdir()} == {"traffic_20261120.db"}  # tmp도 남지 않는다


def test_main_smoke_runs_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # CLI 전체 경로(backup(now_kst()) 포함). 원본·백업 모두 tmp로 돌려 운영 DB를 쓰지 않는다.
    src_db = tmp_path / "src.db"
    c = connect(src_db, create=True)
    init_db(c)
    c.close()
    monkeypatch.setenv("DB_PATH", str(src_db))  # conn=None이 여는 원본 연결의 대상
    monkeypatch.setattr(
        backup_db, "get_settings", lambda: Settings(backup_dir=str(tmp_path / "backup"))
    )

    assert backup_db.main() == 0
    assert (tmp_path / "backup" / f"traffic_{now_kst().date():%Y%m%d}.db").exists()


def test_conn_none_uses_connect_and_closes(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = connect(tmp_path / "src.db", create=True)
    init_db(c)

    class Wrapper:
        """close 호출을 기록하는 최소 대역(테스트 안에서만 쓴다)."""

        def __init__(self, inner: sqlite3.Connection) -> None:
            self._inner = inner
            self.closed = False

        def backup(self, target: sqlite3.Connection) -> None:
            self._inner.backup(target)

        def close(self) -> None:
            self.closed = True
            self._inner.close()

    w = Wrapper(c)
    monkeypatch.setattr(backup_db, "connect", lambda: w)
    p = backup_db.backup(NOW)
    assert p.exists()
    assert w.closed  # conn=None이면 함수가 끝날 때 닫는다 (C-06)
