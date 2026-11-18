"""공용 pytest fixture. 합성 픽스처는 테스트 전용이다(synthetic)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.fixtures.synthetic_db import build_fixture_db

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_db(tmp_path: Path) -> Path:
    """합성 DB 파일 경로."""
    return build_fixture_db(tmp_path / "fixture.db")


@pytest.fixture
def fixture_conn(fixture_db: Path) -> Iterator[sqlite3.Connection]:
    """합성 DB 연결(row_factory=Row, foreign_keys=ON)."""
    conn = sqlite3.connect(fixture_db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    yield conn
    conn.close()


@pytest.fixture
def its_sample_xml() -> bytes:
    return (FIXTURE_DIR / "its_sample_synthetic.xml").read_bytes()


@pytest.fixture
def its_partial_xml() -> bytes:
    return (FIXTURE_DIR / "its_sample_partial_synthetic.xml").read_bytes()
