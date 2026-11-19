"""내부 Streamlit 대시보드 v0 (SPEC 9.1~9.3). 실행: `streamlit run dashboard/app.py`

DB는 읽기 전용으로 연다. 화면에 예시 값이나 임의 수치를 넣지 않고, 값이 없으면 '-'로 표시한다.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# `streamlit run dashboard/app.py`는 스크립트 폴더(dashboard/)를 sys.path에 넣으므로 저장소 루트를 추가한다.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st  # noqa: E402

from common.timeutil import now_kst, to_iso  # noqa: E402
from config.settings import get_settings  # noqa: E402
from dashboard.data import (  # noqa: E402
    DASH,
    collection_status,
    current_table,
    delay_minutes,
    latest_available_at,
)
from dashboard.style import status_text_color  # noqa: E402


@st.fragment(run_every=60)
def render() -> None:
    """화면 전체를 그린다. 60초마다 다시 실행된다."""
    from database.db import connect  # Task 4 산출물. 화면 렌더 시점에만 필요하다.

    s = get_settings()
    now = now_kst()
    try:
        conn = connect(readonly=True)
    except sqlite3.Error as e:
        st.error(f"DB를 열 수 없다: {e}")
        return
    try:
        latest = latest_available_at(conn, now)
        delay = delay_minutes(latest, now)

        c1, c2 = st.columns(2)
        c1.metric("조회 시각", to_iso(now))
        c2.metric("최신 데이터 시각", to_iso(latest) if latest else DASH)
        if delay is None:
            st.warning("집계 데이터 없음")
        elif delay >= s.stale_minutes:
            st.warning(f"데이터 {int(delay)}분 지연")

        st.subheader("구간별 현재 속도·예측 (km/h)")
        st.caption("상태는 속도 기준 파생값(SPEC 9.2). 예측은 기준 모델(baseline_persistence).")
        # 상태 열에만 등급별 글씨색을 입힌다. 데이터 함수(current_table)는 순수하게 값을 유지한다.
        st.dataframe(
            current_table(conn, now, s).style.map(status_text_color, subset=["상태"]),
            hide_index=True,
        )

        st.subheader("최근 수집 결과")
        log = collection_status(conn)
        if log.empty:
            st.write(DASH)
        else:
            st.dataframe(log, hide_index=True)
    except sqlite3.Error as e:
        st.error(f"조회 실패: {e}")
    finally:
        conn.close()


st.set_page_config(page_title="창원대로 교통 대시보드 (내부)", layout="wide")
st.title("창원대로 교통 대시보드 (내부)")
render()
