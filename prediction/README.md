# prediction

`segment_traffic_5min`(전처리 결과)을 읽어 구간 속도를 예측하고 `traffic_prediction`에 저장하며,
지난 예측의 실제값을 채우고(`traffic_prediction.actual_value`) 성능을 `model_evaluation`에 기록한다.
쓰기 소유 테이블: `traffic_prediction`, `model_registry`, `model_evaluation`.

## 기준 모델 3종 (C-04 v1, SPEC 8.2)

| model_version | 예측값 | skipped 조건 |
|---|---|---|
| `baseline_persistence` | 최신 사용 가능 bin의 speed | bin 없음, stale, speed NULL |
| `baseline_recent15` | 최신 사용 가능 bin 포함 직전 15분(3 bin) 중 speed가 있는 값의 평균 | 그런 값이 2개 미만 |
| `baseline_dow_mean` | `available_at ≤ now` 과거 데이터에서 target_time과 같은 요일·같은 HH:MM bin의 speed 평균(`imputed` 제외) | 값이 있는 서로 다른 주가 3주(`dow_mean_min_weeks`) 미만 |

- 세 모델 모두 `model_registry.horizon=0`, `target_var='speed'`, `is_active=1`이고, 같은 `base_time`으로 매 실행마다 함께 저장한다.
- `base_time`은 `available_at ≤ now`이고 stale(10분)이 아닌 최신 bin. 없으면 `floor_5min(now) − 5분`.
- 입력 품질 `input_quality`: 근거 bin flag가 `ok`면 `ok`, `partial`·`unweighted`·`imputed`면 `degraded`, 예측 불가면 `skipped`(predicted_value NULL). dow_mean은 표본 수로 판단한다(충족하면 `ok`).
- skipped 행은 같은 키로 다시 예측할 때 덮어쓴다(늦게 도착한 bin으로 채움). `ok`·`degraded` 행은 덮어쓰지 않는다.

## 실제값 갱신 (backfill)

- 실제값은 같은 구간·`bin_time == target_time`이고 `available_at ≤ now`, speed NOT NULL,
  flag가 `imputed`·`missing`이 아닌 bin에서만 채운다(보정값을 실제값처럼 쓰지 않는다).
- 대상은 `now − backfill_lookback_hours`(6시간) 이후의 target뿐이다.
- 예측값이 NULL(skipped)이면 실제값만 넣고 오차는 NULL로 둔다.

## 평가 (`model_evaluation`)

`prediction.evaluate(now, conn=None, days=7)` — 기간 `[now − days, now)`의 예측 중
`actual_value`·`predicted_value`가 모두 있고, target_time이 평일·비공휴일(`calendar_info.is_holiday`)
이며 `eval_window`(07:00~09:00, 양끝 포함) 안인 것만 평가한다. `calendar_info`에 해당 날짜 행이
없으면 주말만 제외하고 경고를 남긴다.

- 행 단위: (model_version, eval_type=`live`, period, segment_id NULL=전체 또는 구간, regime).
  horizon은 컬럼이 없으므로 `regime` 값에 `h{분}:` 접두어로 표현한다(예: `h15:all`).
- regime(실제값 기준): `all`, `free_flow`(grade=free), `congested`(grade=jam),
  `congestion_onset`(target − 15분 bin 실제 speed 대비 `1 − congestion_onset_drop` 이하 하락).
- 지표: `mae`, `rmse`, `wape = Σ|pred − actual| / Σ|actual|`(분모 0이면 NULL),
  `grade_accuracy = grade(pred) == grade(actual)` 비율(`common.grades.grade`).
- 같은 (model_version, eval_type, period_end 날짜, segment_id, regime) 행이 있으면 교체한다.
  표본이 0인 조합은 행을 만들지 않는다.
- 합성 데이터로 계산한 지표를 실제 성능으로 보고하지 않는다(C-04 불변 조건).

## 코드 위치

| 무엇 | 어디 |
|---|---|
| 공개 진입점 `predict_latest`, `backfill_actuals`, `evaluate` (C-06) | `prediction/__init__.py` |
| 모델 버전 상수, registry 등록, 최신 bin 선택, 예측 행 저장(skipped 덮어쓰기), backfill | `prediction/baseline.py` |
| recent15(최근 15분 평균), dow_mean(과거 동일 요일·시간대 평균) | `prediction/baselines.py` |
| 평가(기간 필터, regime, 지표, `model_evaluation` 저장) | `prediction/evaluate.py` |
| 테스트 | `tests/prediction/` (`test_persistence.py`, `test_baselines.py`, `test_evaluate.py`) |

## 실행

매 5분 수집 직후 `predict_latest(now)` → `backfill_actuals(now)`(스케줄러가 호출).
평가는 매일 1회(예: 10:05) `evaluate(now, days=7)`.

테스트: `.venv\Scripts\python -m pytest tests/prediction -q`
