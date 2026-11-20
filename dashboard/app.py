"""내부 Streamlit 대시보드 v0 (SPEC 9.1~9.3). 실행: `streamlit run dashboard/app.py`

DB는 읽기 전용으로 연다. 화면에 예시 값이나 임의 수치를 넣지 않고, 값이 없으면 '-'로 표시한다.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

# `streamlit run dashboard/app.py`는 스크립트 폴더(dashboard/)를 sys.path에 넣으므로 저장소 루트를 추가한다.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st  # noqa: E402
import pandas as pd  # noqa: E402

from common.timeutil import now_kst, to_iso  # noqa: E402
from config.settings import get_settings  # noqa: E402
from dashboard.data import (  # noqa: E402
    DASH,
    active_models,
    collection_rates,
    collection_status,
    current_table,
    default_model_index,
    delay_minutes,
    evaluation_table,
    heatmap,
    latest_available_at,
    segment_delays,
    timeseries,
    timeseries_status,
)
from dashboard.style import status_text_color  # noqa: E402


@st.fragment(run_every=60)
def render() -> None:
    """화면 전체를 그린다. 60초마다 다시 실행된다."""
    from database.db import connect  # Task 4 산출물. 화면 렌더 시점에만 필요하다.
    import plotly.graph_objects as go

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
        # 최근 수집 시각
        col_row = conn.execute("SELECT started_at FROM collection_log ORDER BY started_at DESC LIMIT 1").fetchone()
        latest_collect = col_row[0] if col_row else None

        c1, c2, c3 = st.columns(3)
        c1.metric("조회 시각", to_iso(now))
        c2.metric("최신 데이터 시각", to_iso(latest) if latest else DASH)
        c3.metric("최근 수집 시작", latest_collect if latest_collect else DASH)
        if delay is None:
            st.warning("집계 데이터 없음")
        elif delay >= s.stale_minutes:
            st.warning(f"데이터 {int(delay)}분 지연")

        tab_current, tab_timeseries, tab_performance = st.tabs(["현재", "시계열", "성능"])

        with tab_current:
            st.subheader("구간별 현재 속도·예측 (km/h)")
            st.caption("상태는 속도 기준 파생값(SPEC 9.2). 예측은 기준 모델(baseline_persistence).")
            df_cur = current_table(conn, now, s)
            # 품질 열이 보정/부분이면 전체 행을 회색으로 표시
            def _row_style(row):
                degraded = row.get("품질") in ("보정", "부분")
                styles = {}
                for col in row.index:
                    if col == "상태":
                        if degraded:
                            styles[col] = "color: #6e6e6e;"
                        else:
                            styles[col] = status_text_color(str(row[col]))
                    else:
                        if degraded:
                            styles[col] = "color: #6e6e6e;"
                        else:
                            styles[col] = ""
                return pd.Series(styles)
            styled = df_cur.style.apply(_row_style, axis=1)
            st.dataframe(styled, hide_index=True)

            st.subheader("최근 수집 결과")
            log = collection_status(conn)
            if log.empty:
                st.write(DASH)
            else:
                st.dataframe(log, hide_index=True)

        with tab_timeseries:
            st.subheader("시계열 그래프")
            # 구간 선택
            segs = conn.execute("SELECT segment_id FROM road_segment WHERE is_target = 1 ORDER BY seq").fetchall()
            seg_options = [r[0] for r in segs]
            seg = st.selectbox("구간", seg_options, index=0)
            horizon = st.selectbox("horizon(분)", list(s.horizons), index=2)
            # 모델 선택 (활성 모델 조회)
            models = active_models(conn)
            if not models:
                st.info("활성 모델이 없습니다.")
                models = ["baseline_persistence"]
            default_idx = default_model_index(models)
            model_v = st.selectbox("모델", models, index=default_idx)
            # 시간 범위 (간단하게 24시간 전~지금)
            start = now - timedelta(days=1)
            end = now
            df_ts = timeseries(conn, seg, start, end, int(horizon), model_v, now)
            status = timeseries_status(df_ts)
            if status == "empty":
                st.info("선택한 조건에 데이터가 없습니다.")
            else:
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df_ts["시각"], y=df_ts["실제"], name="실제", mode="lines+markers"))
                fig.add_trace(go.Scatter(x=df_ts["시각"], y=df_ts["예측"], name="예측", mode="lines+markers"))
                fig.update_layout(xaxis_title="시각", yaxis_title="속도(km/h)", legend=dict(orientation="h"))
                st.plotly_chart(fig, width="stretch")
                if status == "actual_only":
                    st.info("이 모델은 아직 예측이 없습니다(표본 부족 등).")
                elif status == "prediction_only":
                    st.info("실제값이 없습니다.")

            st.subheader("속도 히트맵")
            start_h = now - timedelta(days=1)
            end_h = now
            df_hm = heatmap(conn, start_h, end_h, now)
            if df_hm.empty:
                st.info("히트맵 데이터가 없습니다.")
            else:
                # Plotly Heatmap
                fig_h = go.Figure(data=go.Heatmap(z=df_hm.values, x=df_hm.columns, y=df_hm.index, colorscale="Viridis", hoverongaps=False))
                fig_h.update_layout(xaxis_title="구간", yaxis_title="시각")
                st.plotly_chart(fig_h, width="stretch")

        with tab_performance:
            st.subheader("수집 성공률(평일 06:00~10:00)")
            today_date = now.date()
            df_rates = collection_rates(conn, today_date, days=7)
            # 표시용 준비
            # rate_window 종료 시각 확인
            rate_window = s.rate_window
            # 종료 시각 파싱
            def _parse_hhmm(s_str):
                h, m = map(int, s_str.split(":"))
                return h * 60 + m
            end_minutes = _parse_hhmm(rate_window[1])
            now_minutes = now.hour * 60 + now.minute
            is_today_incomplete = (today_date == now.date() and now_minutes < end_minutes)
            # 성공률 % 표시
            display_rows = []
            for _, row in df_rates.iterrows():
                d = row["날짜"]
                is_service = bool(row["수집일"])
                rate_val = row["성공률"]
                if not is_service:
                    rate_disp = "-"
                elif pd.isna(rate_val):
                    rate_disp = "-"
                else:
                    if d == today_date and is_today_incomplete:
                        rate_disp = "집계 중"
                    else:
                        rate_disp = f"{rate_val * 100:.1f}%"
                display_rows.append({
                    "날짜": d,
                    "수집일": "예" if is_service else "아니오",
                    "기대": int(row["기대"]),
                    "관측": int(row["관측"]),
                    "성공률": rate_disp,
                })
            df_disp = pd.DataFrame(display_rows)
            # 목표 미만 강조
            def _style_row(r):
                # 성공률 문자열 파싱
                val = r["성공률"]
                styles = {}
                if val not in ("-", "집계 중"):
                    try:
                        pct = float(val.rstrip("%"))
                    except:
                        pct = None
                    if pct is not None and pct < s.rate_target * 100:
                        styles["성공률"] = "color: red; font-weight: bold;"
                return pd.Series(styles)
            styled_rates = df_disp.style.apply(_style_row, axis=1)
            st.dataframe(styled_rates, hide_index=True)

            st.subheader("모델 성능 요약")
            df_perf = evaluation_table(conn, days=7)
            if df_perf.empty:
                st.info("평가 데이터가 없습니다.")
            else:
                st.dataframe(df_perf, hide_index=True)
    except sqlite3.Error as e:
        st.error(f"조회 실패: {e}")
    finally:
        conn.close()


st.set_page_config(page_title="창원대로 교통 대시보드 (내부)", layout="wide")
st.title("창원대로 교통 대시보드 (내부)")
render()
