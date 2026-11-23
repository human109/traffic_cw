"""D-COL-08: 같은 회차에 도착한 관측(collected_at > 회차 now)이 전처리·예측에 놓치지 않는지 확인한다.

진입점만 사용한다(collector.run_once, preprocessing.run, prediction.*, scheduler.run_pipeline).
합성 픽스처(fixture_conn, its_sample_xml)만 쓴다 — synthetic, 테스트 전용.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from collector import run_once, scheduler
from collector.base import FetchResult
from collector.its import ItsAdapter
from common.timeutil import KST
from config.settings import Settings

preprocessing = pytest.importorskip("preprocessing")
if not hasattr(preprocessing, "run"):
    pytest.skip("preprocessing.run 미구현", allow_module_level=True)

import prediction  # noqa: E402

NOW = datetime(2026, 11, 16, 7, 5, 30, tzinfo=KST)  # 회차 스케줄 시각(xx:x0:30)


class _FixtureAdapter(ItsAdapter):
    """네트워크 대신 저장된 합성 응답을 돌려주는 어댑터."""

    def __init__(self, settings: Settings, body: bytes) -> None:
        super().__init__(settings)
        self._body = body

    def fetch(self, now: datetime) -> FetchResult:
        return FetchResult(body=self._body, http_status=200, error=None)


def test_same_round_latest_bin_ok(
    fixture_conn: sqlite3.Connection, its_sample_xml: bytes, tmp_path: Path
) -> None:
    """collected_at이 회차 now보다 3초 늦은 관측도 같은 회차에 최신 bin을 ok로 만든다.

    결함 재현(D-COL-08): collect가 10:00:33에 관측을 저장해도 preprocess에 10:00:30을 넘기면
    as-of 규칙이 그 관측을 배제해 최신 bin이 forward fill(imputed)이 됐다. collect 종료 후
    시각을 as-of로 넘기면 같은 회차에서 ok가 된다(미래 정보 불변식은 그대로 — 그 시각에 실제로
    가진 데이터만 쓴다).
    """
    settings = dataclasses.replace(
        Settings(),
        its_api_key="dummy",
        raw_dir=str(tmp_path / "raw"),
        its_store_road_names=("합성도로",),
    )
    # 최신 두 bin(06:55, 07:00)의 관측을 빼고 이전 bin은 남긴다.
    # → 06:55는 결측(이번 회차에도 관측 없음), 07:00는 이번 회차 수집분이 채운다.
    fixture_conn.execute(
        "DELETE FROM traffic_observation WHERE source_timestamp >= '2026-11-16T06:55:00+09:00'"
    )
    fixture_conn.commit()

    clock = [NOW]

    def collect(t: datetime) -> object:
        clock[0] = clock[0] + timedelta(seconds=3)  # 실제 응답은 회차 now보다 3초 늦게 도착한다
        return run_once(
            t,
            conn=fixture_conn,
            adapter=_FixtureAdapter(settings, its_sample_xml),
            settings=settings,
            clock=lambda: clock[0],
        )

    steps = [
        ("collect", collect),
        ("preprocess", lambda until: preprocessing.run(until, conn=fixture_conn)),
        ("backfill", lambda now: prediction.backfill_actuals(now, conn=fixture_conn)),
        ("predict", lambda now: prediction.predict_latest(now, conn=fixture_conn)),
    ]
    results = scheduler.run_pipeline(NOW, steps, clock=lambda: clock[0])
    assert all(not v.startswith("error:") for v in results.values()), results

    # 최신 bin(07:00, 관측은 07:05:33 도착)이 이번 회차에 ok로 집계됐다
    row = fixture_conn.execute(
        "SELECT quality_flag, is_imputed, available_at FROM segment_traffic_5min"
        " WHERE segment_id = 'S1' AND bin_time = '2026-11-16T07:00:00+09:00'"
    ).fetchone()
    assert row is not None
    assert row["quality_flag"] == "ok"
    assert row["is_imputed"] == 0
    assert row["available_at"] == "2026-11-16T07:05:33+09:00"  # 이번 회차 수집 시각

    # 바로 앞 결측 bin(06:55)은 원래 규칙대로 보정(imputed)된다
    prev = fixture_conn.execute(
        "SELECT quality_flag FROM segment_traffic_5min"
        " WHERE segment_id = 'S1' AND bin_time = '2026-11-16T06:55:00+09:00'"
    ).fetchone()
    assert prev is not None and prev["quality_flag"] == "imputed"

    # persistence 예측도 이번 bin을 실제 입력으로 쓴다(degraded가 아니다)
    pr = fixture_conn.execute(
        "SELECT input_quality FROM traffic_prediction"
        " WHERE segment_id = 'S1' AND model_version = 'baseline_persistence'"
        "   AND base_time = '2026-11-16T07:00:00+09:00'"
    ).fetchone()
    assert pr is not None
    assert pr["input_quality"] == "ok"
