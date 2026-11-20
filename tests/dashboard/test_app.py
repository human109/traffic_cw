"""dashboard.app — Streamlit AppTest 화면 전환·내비게이션·데이터 렌더 테스트.

합성(synthetic) DB를 `DB_PATH` 환경변수로 지정해 AppTest로 구동한다.
화면 전환(query params / `_nav_to`), 그리고 실제 데이터가 있는 경우의 렌더링을 검증한다.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import timedelta
from pathlib import Path

from streamlit.testing.v1 import AppTest

from common.timeutil import now_kst, to_iso
from tests.dashboard.test_data import _insert_bin, _insert_model, _insert_pred
from tests.fixtures.synthetic_db import build_fixture_db

APP_PATH = Path(__file__).resolve().parents[2] / "dashboard" / "app.py"


def _seed_realistic(conn: sqlite3.Connection) -> None:
    """실제 화면과 같은 형식의 최소 데이터 적재.

    - `collection_log.started_at`/`finished_at`: ISO 문자열(`to_iso`)
    - `segment_traffic_5min`: `bin_time`/`available_at`/`speed`/`quality_flag`
    - `traffic_prediction`: `baseline_persistence` 예측(실제값 포함)

    시각은 앱이 실측하는 `now_kst()` 기준으로 잡아 조회 범위 안에 들어오게 한다.
    """
    _insert_model(conn)
    base = now_kst() - timedelta(minutes=30)
    _insert_bin(conn, "S1", base, 44.6, base + timedelta(seconds=40))
    _insert_bin(conn, "S2", base, 30.0, base + timedelta(seconds=40))
    _insert_pred(conn, "S1", base, 15, 44.6, "ok", executed_at=now_kst())
    _insert_pred(conn, "S2", base, 15, 30.0, "ok", executed_at=now_kst())
    conn.execute(
        "INSERT INTO collection_log (source, started_at, finished_at, status, record_count) VALUES (?, ?, ?, 'success', 5)",
        ("synthetic", to_iso(base), to_iso(base + timedelta(seconds=2))),
    )


def _run_app(tmp_path: Path, query_params: dict[str, str] | None = None) -> AppTest:
    db_path = build_fixture_db(tmp_path / "app_fixture.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    _seed_realistic(conn)
    conn.commit()
    conn.close()
    os.environ["DB_PATH"] = str(db_path)
    at = AppTest(script_path=str(APP_PATH), default_timeout=30)
    if query_params:
        for key, value in query_params.items():
            at.query_params[key] = value
    at.run()
    return at


def test_app_default_run_has_controls(tmp_path: Path) -> None:
    at = _run_app(tmp_path)
    assert not at.exception
    assert len(at.segmented_control) >= 1
    assert at.segmented_control[0].value == "현재"
    # 기본 화면(현재)에는 구간 selectbox가 없다.
    assert len(at.selectbox) == 0
    # 현재 화면: 구간별 현재 속도 dataframe + 최근 수집 결과 dataframe
    assert len(at.dataframe) >= 1


def test_app_query_params_open_timeseries(tmp_path: Path) -> None:
    at = _run_app(tmp_path, query_params={"view": "시계열", "seg": "S2"})
    assert not at.exception
    assert at.segmented_control[0].value == "시계열"
    # 첫 번째 selectbox은 시계열 화면의 구간 선택이다.
    assert len(at.selectbox) >= 1
    assert at.selectbox[0].value == "S2"
    # 시계열 화면: 시계열 그래프 + 히트맵 plotly 차트 2개가 그려져야 한다.
    assert len(at.get("plotly_chart")) >= 2


def test_app_query_params_invalid_falls_back(tmp_path: Path) -> None:
    at = _run_app(tmp_path, query_params={"view": "없는화면", "seg": "XX"})
    assert not at.exception
    assert at.segmented_control[0].value == "현재"
    # 잘못된 값 → 기본값(현재 / 첫 대상 구간 S1)으로 fallback 한다.
    assert at.session_state.get("seg") == "S1"


def test_app_nav_to_from_row_click(tmp_path: Path) -> None:
    at = _run_app(tmp_path)
    assert not at.exception
    assert at.segmented_control[0].value == "현재"
    # dataframe 행 클릭은 `_nav_to`에 목적지를 싣고 fragment를 다시 실행한다(실제 UI 선택 대신).
    at.session_state["_nav_to"] = {"view": "시계열", "seg": "S2"}
    at.run()
    assert not at.exception
    assert at.segmented_control[0].value == "시계열"
    assert at.selectbox[0].value == "S2"
    assert at.session_state.get("seg") == "S2"


def test_app_row_click_selection_navigates_to_timeseries(tmp_path: Path) -> None:
    """행 클릭(선택) 시뮬레이션: dataframe 선택 상태 주입 → 시계열 이동, 예외 없이 동작."""
    at = _run_app(tmp_path)
    assert not at.exception
    assert at.segmented_control[0].value == "현재"
    # 합성 픽스처 구간 표 행: S1(0), S2(1), S3(2). S2(행 인덱스 1)를 선택했다고 시뮬레이션.
    at.session_state["seg_table_0"] = {"selection": {"rows": [1], "columns": [], "cells": []}}
    at.run()
    assert not at.exception
    assert at.segmented_control[0].value == "시계열"
    assert at.selectbox[0].value == "S2"
    assert at.session_state.get("seg") == "S2"
    # 시계열 화면: 그래프 + 히트맵 plotly 차트 2개가 그려져야 한다.
    assert len(at.get("plotly_chart")) >= 2
    # 다음 실행에서도 시계열이 유지되고(튕김 없음), 현재 화면으로 돌아가도 예외가 나지 않아야 한다.
    at.run()
    assert not at.exception
    assert at.segmented_control[0].value == "시계열"
    assert at.session_state.get("seg") == "S2"
    at.session_state["view"] = "현재"
    at.run()
    assert not at.exception
    assert at.segmented_control[0].value == "현재"


def test_app_performance_view_renders_with_real_data(tmp_path: Path) -> None:
    at = _run_app(tmp_path, query_params={"view": "성능"})
    assert not at.exception
    assert at.segmented_control[0].value == "성능"
    # 성공률 표 + 모델 성능 요약 dataframe
    assert len(at.dataframe) >= 1
