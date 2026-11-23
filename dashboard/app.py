"""내부 Streamlit 대시보드 v0 (SPEC 9.1~9.3). 실행: `streamlit run dashboard/app.py`

DB는 읽기 전용으로 연다. 화면에 예시 값이나 임의 수치를 넣지 않고, 값이 없으면 '-'로 표시한다.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

# `streamlit run dashboard/app.py`는 스크립트 폴더(dashboard/)를 sys.path에 넣으므로 저장소 루트를 추가한다.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st  # noqa: E402
import pandas as pd  # noqa: E402

from common.timeutil import now_kst  # noqa: E402
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
    format_collection_rates_display,
    format_time_label,
    heatmap,
    latest_available_at,
    parse_nav,
    parse_road,
    segment_delays,
    selection_nav,
    timeseries,
    timeseries_status,
)
from dashboard.style import grade_colorscale, status_badge_css  # noqa: E402

VIEW_OPTIONS = ("현재", "시계열", "성능")
NAV_TO_KEY = "_nav_to"


@st.fragment(run_every=60)
def render() -> None:
    """화면 전체를 그린다. 60초마다 다시 실행된다."""
    from database.db import connect  # Task 4 산출물. 화면 렌더 시점에만 필요하다.
    import plotly.graph_objects as go

    s = get_settings()
    now = now_kst()

    # 연결 자체가 실패하면 finally에서 conn를 닫을 수 없으므로 별도 try/except로 처리한다.
    conn = None
    try:
        conn = connect(readonly=True)
    except sqlite3.Error as e:
        st.error(f"DB 연결 실패: {e}")
        return

    try:
        # 대상 구간 조회 (도로 구분 포함)
        seg_rows = conn.execute(
            "SELECT segment_id, road_name, start_node, end_node, seq FROM road_segment WHERE is_target = 1"
        ).fetchall()
        # 도로 순서: settings.corridors → 목록에 없으면 road_name 순
        road_order_map = {road: i for i, road in enumerate(s.corridors)}
        roads = sorted({r[1] for r in seg_rows}, key=lambda rn: (road_order_map.get(rn, 9999), rn))
        # 도로별 구간 매핑
        road_to_segments: dict[str, list[tuple[int, str, str, str]]] = {}
        seg_to_road: dict[str, str] = {}
        for sid, road_name, start_node, end_node, seq in seg_rows:
            road_to_segments.setdefault(road_name, []).append((seq, sid, start_node, end_node))
            seg_to_road[sid] = road_name
        for road in road_to_segments:
            road_to_segments[road].sort(key=lambda x: x[0])

        # --- 도로 선택 상태 초기화 ---
        if "road" not in st.session_state:
            road = parse_road(st.query_params, roads)
            st.session_state["road"] = road
        else:
            road = st.session_state.get("road")
            if road not in roads:
                road = roads[0] if roads else ""
                st.session_state["road"] = road

        # 도로 선택 UI (하나뿐이면 숨김)
        if len(roads) > 1:
            road_idx = roads.index(road) if road in roads else 0
            road_sel = st.selectbox("도로", roads, index=road_idx, key="road_select")
            if road_sel != st.session_state.get("road"):
                st.session_state["road"] = road_sel
                # 도로 변경 시 구간 초기화
                st.session_state["seg"] = road_to_segments[road_sel][0][1] if road_to_segments.get(road_sel) else ""
                st.query_params["road"] = road_sel
                st.rerun()
            road = st.session_state["road"]
        else:
            # 단일 도로: 선택 컨트롤 숨김, 값 고정
            road = roads[0] if roads else ""
            st.session_state["road"] = road

        # 현재 도로의 구간 목록
        segs_for_road = road_to_segments.get(road, [])
        segs = [(sid, start, end) for _, sid, start, end in segs_for_road]
        seg_ids = [sid for _, sid, _, _ in segs_for_road]

        # --- 화면 전환 ---
        nav = st.session_state.pop("_nav_to", None)
        if nav is not None:
            st.session_state["view"] = nav.get("view") or "시계열"
            new_seg = nav.get("seg") or ""
            # seg 변경 시 도로도 함께 업데이트
            if new_seg in seg_to_road:
                st.session_state["road"] = seg_to_road[new_seg]
            st.session_state["seg"] = new_seg

        if st.session_state.get("view") is None:
            st.session_state["view"], st.session_state["seg"] = parse_nav(st.query_params, seg_ids)

        view = st.session_state.get("view") or "현재"
        seg = st.session_state.get("seg") or (seg_ids[0] if seg_ids else "")

        # view 컨트롤
        view_before = view
        st.segmented_control("화면", list(VIEW_OPTIONS), key="view")
        view = st.session_state.get("view") or view_before

        # 도로·세그먼트·뷰 파라미터 동기화
        if road:
            st.query_params["road"] = road
        st.query_params["view"] = view or "현재"
        st.query_params["seg"] = seg or (seg_ids[0] if seg_ids else "")

        latest = latest_available_at(conn, now, road if road else None)
        delay = delay_minutes(latest, now)
        # 최근 수집 시각
        col_row = conn.execute("SELECT started_at FROM collection_log ORDER BY started_at DESC LIMIT 1").fetchone()
        latest_collect = col_row[0] if col_row else None

        c1, c2, c3 = st.columns(3)
        c1.metric("조회 시각", format_time_label(now, now=now))
        c2.metric("최신 데이터 시각", format_time_label(latest, now=now) if latest else DASH)
        c3.metric("최근 수집 시작", format_time_label(latest_collect, now=now) if latest_collect else DASH)
        if delay is None:
            st.warning("집계 데이터 없음")
        elif delay >= s.stale_minutes:
            st.warning(f"데이터 {int(delay)}분 지연")

        if view == "시계열":
            st.subheader("시계열 그래프")
            if not seg_ids:
                st.info("대상 구간이 없습니다.")
            else:
                seg = seg if seg in seg_ids else seg_ids[0]
                seg_index = seg_ids.index(seg)
                seg_names = {r[0]: f"{r[1]} → {r[2]}" for r in segs}
                seg_label = st.selectbox("구간", seg_ids, index=seg_index, format_func=lambda sid: seg_names.get(sid, sid))
                seg = seg_label
                st.session_state["seg"] = seg
                st.query_params["seg"] = seg
                # 구간 변경 시 도로도 동기화
                seg_road = seg_to_road.get(seg)
                if seg_road and seg_road != road:
                    st.session_state["road"] = seg_road
                    st.query_params["road"] = seg_road
                    st.rerun()
                horizon = st.selectbox("horizon(분)", list(s.horizons), index=2)
                # 모델 선택 (활성 모델 조회)
                models = active_models(conn)
                if not models:
                    st.info("활성 모델이 없습니다.")
                    models = ["baseline_persistence"]
                default_idx = default_model_index(models)
                model_v = st.selectbox("모델", models, index=default_idx)
                period = st.selectbox("기간", ["6시간", "24시간", "3일"], index=1)
                period_hours = {"6시간": 6, "24시간": 24, "3일": 72}
                # 시간 범위 (선택 기간 전~지금)
                start = now - timedelta(hours=period_hours[period])
                end = now
                df_ts = timeseries(conn, seg, start, end, int(horizon), model_v, now)
                status = timeseries_status(df_ts)
                if status == "empty":
                    st.info("선택한 조건에 데이터가 없습니다.")
                else:
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=df_ts["시각"], y=df_ts["실제"], name="실제", mode="lines+markers"))
                    # 예측은 점선(실제 선 위에 덧붙인 보조선)
                    fig.add_trace(go.Scatter(x=df_ts["시각"], y=df_ts["예측"], name="예측", mode="lines", line=dict(dash="dash")))
                    # 등급 띠: 정체/서행/원활 구간을 수평 띠로 표시(SPEC 9.2, 경계값은 config/settings.py).
                    fig.add_hrect(y0=0.0, y1=float(s.grade_slow_min_kmh), fillcolor="rgba(198, 40, 40, 0.08)", line_width=0)
                    fig.add_hrect(y0=float(s.grade_slow_min_kmh), y1=float(s.grade_free_min_kmh), fillcolor="rgba(245, 127, 17, 0.08)", line_width=0)
                    # 원활 띠 위쪽도 표시 상한(`chart_max_kmh`)까지, y축 범위는 데이터 최대와 상한 중 큰 값.
                    y_max = float(s.chart_max_kmh)
                    for col in ("실제", "예측"):
                        vals = pd.to_numeric(df_ts[col], errors="coerce").dropna()
                        if len(vals):
                            y_max = max(y_max, float(vals.max()))
                    fig.add_hrect(y0=float(s.grade_free_min_kmh), y1=y_max, fillcolor="rgba(46, 125, 50, 0.08)", line_width=0)
                    fig.update_yaxes(range=[0.0, y_max])
                    fig.update_layout(xaxis_title="시각", yaxis_title="속도(km/h)", legend=dict(orientation="h"))
                    st.plotly_chart(fig, width="stretch")
                    if status == "actual_only":
                        st.info("이 모델은 아직 예측이 없습니다(표본 부족 등).")
                    elif status == "prediction_only":
                        st.info("실제값이 없습니다.")

                st.subheader("속도 히트맵")
                start_h = now - timedelta(days=1)
                end_h = now
                df_hm = heatmap(conn, start_h, end_h, now, road if road else None)
                if df_hm.empty:
                    st.info("히트맵 데이터가 없습니다.")
                else:
                    # Plotly Heatmap: 빨강(저속/정체) → 초록(고속/원활) 연속색, zmin 0·zmax 고정.
                    fig_h = go.Figure(
                        data=go.Heatmap(
                            z=df_hm.values,
                            x=df_hm.columns,
                            y=df_hm.index,
                            colorscale=grade_colorscale(float(s.chart_max_kmh), float(s.grade_slow_min_kmh), float(s.grade_free_min_kmh)),
                            zmin=0,
                            zmax=float(s.chart_max_kmh),
                            hoverongaps=False,
                        )
                    )
                    seg_names_hm = {r[0]: f"{r[1]} → {r[2]}" for r in segs}
                    fig_h.update_layout(
                        xaxis=dict(
                            title="구간",
                            ticktext=[seg_names_hm.get(c, c) for c in df_hm.columns],
                            tickvals=list(df_hm.columns),
                        ),
                        yaxis_title="시각",
                    )
                    st.plotly_chart(fig_h, width="stretch")

        elif view == "성능":
            st.subheader("수집 성공률(평일 06:00~10:00)")
            today_date = now.date()
            df_rates = collection_rates(conn, today_date, days=7, road_name=road if road else None)
            rate_window = s.rate_window
            display_rows = format_collection_rates_display(df_rates, s.rate_target, now, rate_window[1])

            def _style_rate_row(r) -> pd.Series:
                styles = {}
                if bool(r.get("미달")):
                    styles["성공률"] = "color: red; font-weight: bold;"
                return pd.Series(styles)

            styled_rates = display_rows.style.apply(_style_rate_row, axis=1)
            st.dataframe(styled_rates, hide_index=True)

            st.subheader("모델 성능 요약")
            df_perf = evaluation_table(conn, days=7, road_name=road if road else None)
            if df_perf.empty:
                st.info("평가 데이터가 없습니다.")
            else:
                st.dataframe(df_perf, hide_index=True)

        else:
            st.subheader("구간별 현재 속도·예측 (km/h)")
            st.caption("상태는 속도 기준 파생값(SPEC 9.2). 예측은 기준 모델(baseline_persistence).")
            st.caption("행을 클릭하면 그 구간의 시계열로 이동합니다.")
            df_cur = current_table(conn, now, s, road if road else None)
            # 품질 열이 보정/부분이면 전체 행을 회색으로 표시
            def _row_style(row):
                degraded = row.get("품질") in ("보정", "부분")
                styles = {}
                for col in row.index:
                    if col == "상태":
                        if degraded:
                            styles[col] = "color: #6e6e6e;"
                        else:
                            styles[col] = status_badge_css(str(row[col]))
                    else:
                        if degraded:
                            styles[col] = "color: #6e6e6e;"
                        else:
                            styles[col] = ""
                return pd.Series(styles)
            styled = df_cur.style.apply(_row_style, axis=1)
            nav_seq = int(st.session_state.get("_nav_seq") or 0)
            table_key = f"seg_table_{nav_seq}"
            sel_state = st.session_state.get(table_key)
            sel_rows: list[int] = []
            if isinstance(sel_state, dict):
                sel_inner = sel_state.get("selection")
                if isinstance(sel_inner, dict):
                    raw_rows = sel_inner.get("rows") or []
                    if isinstance(raw_rows, list):
                        sel_rows = [int(r) for r in raw_rows if isinstance(r, int)]
            if sel_rows:
                sid = str(df_cur.iloc[sel_rows[0]]["구간"])
                st.session_state[NAV_TO_KEY] = selection_nav(sid)
                st.session_state["_nav_seq"] = nav_seq + 1
                # AppTest 등 full-run 컨텍스트에서도 안전하게 동작하도록 full rerun으로 전환.
                st.rerun()
            st.dataframe(styled, hide_index=True, on_select="rerun", selection_mode="single-row", key=table_key)

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


st.set_page_config(page_title="교통 대시보드 (내부)", layout="wide")
st.title("교통 대시보드 (내부)")
render()
