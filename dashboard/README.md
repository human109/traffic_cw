# dashboard — 내부 대시보드 v0

소유: `dev-dashboard`. 근거: SPEC 9.1~9.3. DB는 **읽기 전용**으로만 연다.

## 실행

저장소 루트에서:

```powershell
.venv\Scripts\streamlit run dashboard/app.py
```

DB 경로는 `config.settings.get_settings().db_path`(기본 `data/traffic.db`, 환경변수 `DB_PATH`)를 쓴다.

## 화면 구성

1. **상단**: 조회 시각, 최신 데이터 시각(속도가 있는 `segment_traffic_5min` bin의 `available_at` 최대값. `missing` bin은 제외), 최근 수집 시작 시각.
   세 값은 `dashboard.data.format_time_label`로 짧게 표시한다(오늘 `HH:MM`, 아니면 `MM-DD HH:MM`).
   최신 데이터가 `stale_minutes`(10분) 이상 늦으면 `데이터 N분 지연` 경고, 집계가 없으면 `집계 데이터 없음` 경고.

2. **화면 전환 (`st.segmented_control`, key=`view`)**: `현재` / `시계열` / `성능`.
   초기값은 `st.query_params`의 `view`, `seg`로 정하고, `dashboard.data.parse_nav`이
   잘못된 값은 기본값(현재 / 첫 대상 구간)으로 떨어뜨린다. 예: `?view=시계열&seg=S3`로 바로 열림.
   값이 바뀌면 세그먼트 컨트롤(`key="view"`)·`st.session_state`·`st.query_params`를 함께 갱신한다.
   매 실행 끝에 `st.query_params["view"]`/`["seg"]`를 현재 값으로 동기화하고, 컨트롤 선택 해제(None)면
   이전 view를 유지한다.

   - 현재 화면의 구간 표에서 행을 클릭하면 해당 구간의 시계열로 이동한다.
     선택 행의 구간 ID를 `seg`로 세팅하고 `view="시계열"`로 바꾼 뒤 `st.rerun()`
     한다(`dashboard.data.selection_nav`이 목적지를 만든다). 목적지는 세션 상태
     `st.session_state["_nav_to"]`에 심고, 화면 전환 컨트롤 생성 전에 소비한다.
   - `시계열` 화면의 구간 selectbox는 `seg`를 기본값으로 쓰고 라벨에 구간 이름(`start → end`)을 함께 쓴다.

3. **현재**: 구간별 현재 속도·예측 표 + 하단 최근 수집 결과.
   열: 구간, 이름, 현재 속도, 상태(원활/서행/정체, 속도 기준 파생값), 품질(`ok`/`보정`/`부분`/`-`), 5·10·15·30분 후 예측.
   품질이 `보정`/`부분`인 행은 회색으로 표시(degraded/imputed). 예측은 최신 bin의 `bin_time`을 `base_time`으로 하는 `baseline_persistence` 예측 중 `executed_at ≤ 조회 시각`인 것이다.
   상태 열은 `dashboard/style.status_badge_css` 배지를 쓴다(WCAG AA 대비 ≥ 4.5:1).

4. **시계열**: 구간·horizon·기간(6시간/24시간/3일)·모델 선택 시계열 그래프(실제 실선 + 예측 점선, 등급 띠 `fig.add_hrect`, 기간 선택).
   실제값은 보정·missing bin 제외(보정값 사용 안 함). 모델 기본 선택은 `default_model_index`로 `baseline_persistence` 우선.
   데이터 존재 판정은 `timeseries_status`로 분류: `both`(실제·예측 모두), `actual_only`(예측 없음 → "이 모델은 아직 예측이 없습니다…" 안내, 실제값만 표시), `prediction_only`, `empty`(“선택한 조건에 데이터가 없습니다”). 히트맵은 보정값 포함, `available_at ≤ 조회 시각`만 반영.
   그래프는 등급 띠(정체/서행/원활, `config/settings.py`의 `grade_slow_min_kmh`/`grade_free_min_kmh`)를 `add_hrect`로,
   원활 띠 위쪽은 표시 상한(`config/settings.py`의 `chart_max_kmh`)/데이터 최대 중 큰 값까지, y축 범위를 잡는다.
   히트맵은 등급 경계 기준 단계색(0 ~ `grade_slow_min_kmh` 빨강, ~ `grade_free_min_kmh` 주황, 그 이상 초록)으로
   `zmin=0`, `zmax=chart_max_kmh`를 쓰고 구간 이름 축을 쓴다.

5. **성능**: 상단 “수집 성공률(평일 06:00~10:00)” 표(`collection_rates` → C-06 `scripts.collection_rate.rate`, 표시는 `dashboard.data.format_collection_rates_display`)와 하단 `model_evaluation` 최신 행 + 기준 모델 대비 개선율.

화면은 60초마다 자동 갱신한다(`st.fragment(run_every=60)`).

## 표시 규칙

- 값이 없거나 예측이 `skipped`이면 `-`. 임의 수치·예시 값을 넣지 않는다.
- 혼잡 등급 경계는 `config/settings.py`의 `grade_free_min_kmh`, `grade_slow_min_kmh`(공개 화면과 같은 값).
- 숫자는 정수로 반올림해 표시한다.
- 품질이 `보정`(imputed) 또는 `부분`(partial/unweighted)인 구간은 회색 표시.

## 코드 구조

- `data.py`: 조회·가공 순수 함수. `conn`을 인자로 받으므로 테스트에서 합성 DB를 넘긴다. 주요 함수:
  - `parse_nav(params, segments)` → query parameter(`view`, `seg`)를 화면 상태(`view`, `seg`)로 바꾼다. 잘못된 값은 기본값으로 떨어뜨린다.
  - `selection_nav(segment_id)` → 구간 표 행 선택 → 시계열 이동 목적지.
  - `collection_rates`, `format_collection_rates_display`, `default_model_index`, `timeseries_status`, `timeseries`, `heatmap`, `evaluation_table`, `segment_delays`, `active_models` 등
- `style.py`: 상태 문자열 → 글씨색(`status_text_color`), 상태 배지 CSS(`status_badge_css`, WCAG AA 대비 ≥ 4.5:1) 순수 함수.
- `app.py`: Streamlit 화면. `database.db.connect(readonly=True)`로 연결. Plotly 차트는 `width="stretch"` 사용.

테스트: `.venv\Scripts\python -m pytest tests/dashboard -q`

## 변경 이력

| 작업 ID | 날짜 | 요약 |
|---|---|---|
| D-DSH-02 | 2026-11-20 | 수집 성공률 표 추가, `collection_rates` 도입, 성능 탭 상단 표 및 강조·집계 중 표시 |
| D-DSH-03 | 2026-11-20 | 시계열 기본 모델 `baseline_persistence` 고정, `timeseries_status` 기반 표시 판정, `width="stretch"` 적용 |
| D-DSH-04 | 2026-11-20 | URL 파라미터 기반 뷰 전환, 구간 표 클릭 시 시계열 이동, 시간 라벨 포맷, 배지 대비, 성공률 표시 함수 분리, 시계열 등급 띠·히트맵 색상 개선 |
