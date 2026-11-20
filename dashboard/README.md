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
   최신 데이터가 `stale_minutes`(10분) 이상 늦으면 `데이터 N분 지연` 경고, 집계가 없으면 `집계 데이터 없음` 경고.
2. **탭 `현재`**: 구간별 표.
   열: 구간, 이름, 현재 속도, 상태(원활/서행/정체, 속도 기준 파생값), 품질(`ok`/`보정`/`부분`/`-`), 5·10·15·30분 후 예측.
   품질이 `보정`/`부분`인 행은 회색으로 표시(degraded/imputed). 예측은 최신 bin의 `bin_time`을 `base_time`으로 하는 `baseline_persistence` 예측 중 `executed_at ≤ 조회 시각`인 것이다.
3. **탭 `시계열`**: 구간·horizon·모델 선택 시계열 그래프(실제 vs 예측, Plotly). 실제값은 보정·missing bin 제외(보정값 사용 안 함). 모델 기본 선택은 `default_model_index`로 `baseline_persistence` 우선.
   데이터 존재 판정은 `timeseries_status`로 분류: `both`(실제·예측 모두), `actual_only`(예측 없음 → “이 모델은 아직 예측이 없습니다…” 안내, 실제값만 표시), `prediction_only`, `empty`(“선택한 조건에 데이터가 없습니다”). 히트맵은 보정값 포함, `available_at ≤ 조회 시각`만 반영.
4. **탭 `성능`**: 상단 “수집 성공률(평일 06:00~10:00)” 표(`collection_rates` → C-06 `scripts.collection_rate.rate`). 열: 날짜, 수집일, 기대, 관측, 성공률(%). 목표는 `settings.rate_target`, 미달 강조, 비수집일 ‘-’, 오늘 `rate_window` 종료 전 ‘집계 중’. 하단에 `model_evaluation` 최신 행과 기준 모델 대비 개선율.

화면은 60초마다 자동 갱신한다(`st.fragment(run_every=60)`).

## 표시 규칙

- 값이 없거나 예측이 `skipped`이면 `-`. 임의 수치·예시 값을 넣지 않는다.
- 혼잡 등급 경계는 `config/settings.py`의 `grade_free_min_kmh`, `grade_slow_min_kmh`(공개 화면과 같은 값).
- 숫자는 정수로 반올림해 표시한다.
- 품질이 `보정`(imputed) 또는 `부분`(partial/unweighted)인 구간은 회색 표시.

## 코드 구조

- `data.py`: 조회·가공 순수 함수. `conn`을 인자로 받으므로 테스트에서 합성 DB를 넘긴다. 주요 함수:
  - `collection_rates(conn, today, days)` → C-06 `scripts.collection_rate.rate` 래퍼
  - `default_model_index(models)` → `baseline_persistence` 우선 기본 선택
  - `timeseries_status(df)` → both/actual_only/prediction_only/empty 분류
  - `timeseries`, `heatmap`, `evaluation_table`, `segment_delays`, `active_models` 등
- `style.py`: 상태 문자열 → 글씨색(hex) 매핑 순수 함수(`status_text_color`). `data.py`는 값만 유지하고 색은 여기서.
- `app.py`: Streamlit 화면. `database.db.connect(readonly=True)`로 연결. Plotly 차트는 `width="stretch"` 사용. 상태 열은 `style.py` 매핑으로 색을 입힌다.

테스트: `.venv\Scripts\python -m pytest tests/dashboard -q`

## 변경 이력

| 작업 ID | 날짜 | 요약 |
|---|---|---|
| D-DSH-02 | 2026-11-20 | 수집 성공률 표 추가, `collection_rates` 도입, 성능 탭 상단 표 및 강조·집계 중 표시 |
| D-DSH-03 | 2026-11-20 | 시계열 기본 모델 `baseline_persistence` 고정, `timeseries_status` 기반 표시 판정, `width="stretch"` 적용 |

