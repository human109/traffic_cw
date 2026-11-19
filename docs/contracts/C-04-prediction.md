# C-04 예측 결과와 모델 평가

| 항목 | 내용 |
|---|---|
| 상태 | frozen |
| 버전 | v1.2 |
| 영향 받는 에이전트 | dev-ml, dev-dashboard, (Phase 2) dev-publisher |
| 계약 테스트 | `tests/prediction/`, `tests/integration/` |

## 정의

### 모델 버전 (`model_registry`, `traffic_prediction.model_version`)

| model_version | model_type | 예측값 | 예측 불가(skipped) 조건 |
|---|---|---|---|
| `baseline_persistence` | `baseline_persistence` | 최신 사용 가능 bin의 speed | bin 없음, stale, speed NULL |
| `baseline_recent15` | `baseline_recent15` | 최신 사용 가능 bin을 포함한 직전 3 bin(`recent_mean_minutes`) 중 speed가 있는 값의 평균 | 그런 값이 2개 미만 |
| `baseline_dow_mean` | `baseline_dow_mean` | `available_at ≤ now`, `base_time − 8주 ≤ bin_time ≤ base_time`인 과거 데이터에서, `target_time`과 같은 요일·같은 HH:MM bin의 speed 평균(`imputed` 제외) (v1.2: 8주 하한) | 서로 다른 주가 `dow_mean_min_weeks`(3) 미만 |

- 세 모델 모두 `model_registry.horizon=0`(horizon 공통), `target_var='speed'`, `is_active=1`.
- 세 모델은 같은 `base_time`으로 매 실행마다 함께 저장한다.
- 입력 품질 `input_quality`: 근거 bin flag가 `ok`면 `ok`, `partial`·`unweighted`·`imputed`면 `degraded`, 예측 불가면 `skipped`(predicted_value NULL). dow_mean은 근거 bin 대신 표본 수로 판단하며, 조건을 충족하면 `ok`.
- skipped 행은 같은 키로 다시 예측할 때 덮어쓴다. `ok`·`degraded` 행은 덮어쓰지 않는다.

### 실제값 (backfill)

- `actual_value`는 같은 구간의 `bin_time == target_time`, `available_at ≤ now`, speed NOT NULL, **flag가 `imputed`·`missing`이 아닌** bin에서만 채운다.
- 대상은 `target_time ≥ now − backfill_lookback_hours`.

### 평가 (`model_evaluation`, `prediction.evaluate`)

- 대상 예측: 기간 `[now − days, now)`의 target_time, `actual_value`·`predicted_value` 모두 NOT NULL, target_time이 평일이면서 `calendar_info.is_holiday`가 1이 아니고 `eval_window`(양끝 포함) 안. 해당 날짜의 `calendar_info` 행이 없으면 주말만 제외하고 경고 로그.
- 행 단위: (model_version, horizon, segment_id[NULL=전체], regime).
- **horizon 표현**: 테이블에 horizon 컬럼이 없으므로 `regime` 값에 접두어를 붙인다. `h{분}:{regime}` (예: `h15:all`, `h30:congestion_onset`).
- regime(실제값 기준):
  - `all`: 전체
  - `free_flow`: `grade(actual) == "free"`
  - `congested`: `grade(actual) == "jam"`
  - `congestion_onset`: 같은 구간 `target_time − 15분` bin의 실제 speed가 있고, `actual ≤ 그 값 × (1 − congestion_onset_drop)`
- 지표: `mae`, `rmse`, `wape = Σ|pred − actual| / Σ|actual|`(분모 0이면 NULL), `grade_accuracy = grade(pred) == grade(actual)` 비율(`common.grades.grade`).
- `eval_type='live'`, `period_start`·`period_end`는 to_iso, `evaluated_at = to_iso(now)`. 같은 (model_version, eval_type, period_end의 **날짜**, segment_id, regime) 행이 있으면 교체한다(v1.1: 하루에 여러 번 실행해도 날짜당 1벌만 남긴다).
- 표본이 0인 조합은 행을 만들지 않는다.

## 불변 조건

- 합성 데이터로 계산한 지표를 실제 성능으로 보고하지 않는다.
- 예측·평가는 `available_at ≤ now`인 데이터만 쓴다.

## 변경 이력

| 버전 | 일자 | 변경 | CR 출처 |
|---|---|---|---|
| v1.2 | 2026-11-20 | dow_mean 조회 하한 8주(`prediction.baselines.DOW_MEAN_LOOKBACK_WEEKS`) | D-ML-02 |
| v1.1 | 2026-11-19 | 평가 교체 키를 period_end 날짜 기준으로 명시. dow_mean 표본은 `bin_time ≤ base_time` | Task 4 구현·리뷰 |
| v1 | 2026-11-19 | 기준 모델 3종, backfill 규칙, 평가 행 정의 | Slice 1 계획, Slice 0 리뷰 |
