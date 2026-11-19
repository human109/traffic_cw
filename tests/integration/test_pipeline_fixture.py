"""synthetic: 합성 픽스처로 수집 → 집계 → 예측 → 대시보드 표가 이어지는지 확인한다 (Slice 0 Task 10)."""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from collector import run_once
from collector.base import FetchResult
from collector.its import ItsAdapter
from common.timeutil import KST
from config.settings import get_settings
from dashboard.data import current_table

preprocessing = pytest.importorskip("preprocessing")
if not hasattr(preprocessing, "run"):
    pytest.skip("preprocessing.run 미구현 (Task 6)", allow_module_level=True)

import prediction  # noqa: E402


class _FixtureAdapter(ItsAdapter):
    """네트워크 대신 저장된 합성 응답을 돌려주는 어댑터."""

    def __init__(self, settings, body: bytes) -> None:
        super().__init__(settings)
        self._body = body

    def fetch(self, now: datetime) -> FetchResult:
        return FetchResult(body=self._body, http_status=200, error=None)


def test_fixture_end_to_end(fixture_conn: sqlite3.Connection, its_sample_xml: bytes, tmp_path: Path) -> None:
    settings = dataclasses.replace(get_settings(), its_api_key="dummy", raw_dir=str(tmp_path / "raw"))
    fixture_conn.execute("DELETE FROM traffic_observation")
    fixture_conn.commit()

    result = run_once(
        datetime(2026, 11, 16, 7, 0, 40, tzinfo=KST),
        conn=fixture_conn,
        adapter=_FixtureAdapter(settings, its_sample_xml),
        settings=settings,
    )
    assert result.status in ("success", "partial")
    assert result.record_count == 5

    assert preprocessing.run(datetime(2026, 11, 16, 7, 5, 30, tzinfo=KST), conn=fixture_conn) > 0
    now = datetime(2026, 11, 16, 7, 5, 45, tzinfo=KST)
    assert prediction.predict_latest(now, conn=fixture_conn) > 0

    table = current_table(fixture_conn, now, settings).set_index("구간")
    s1 = table.loc["S1"]
    assert s1["현재 속도"] != "-"
    for col in ("5분 후", "10분 후", "15분 후", "30분 후"):
        assert s1[col] == s1["현재 속도"]  # 현재 속도 유지 모델
    # SYN0000003은 speed가 빈 태그 → S2는 관측 없음 → '-' (0으로 채우지 않음)
    assert table.loc["S2"]["현재 속도"] == "-"
