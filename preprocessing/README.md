# preprocessing

링크 단위 원본 관측(`traffic_observation`)을 구간 x 5분 bin 값(`segment_traffic_5min`)으로 집계한다.
공개 진입점은 `preprocessing.run(until, conn=None, lookback_minutes=60) -> int` 하나다(C-06).

## 흐름 (`preprocessing/aggregate.py`)

| 단계 | 함수 | 내용 |
|---|---|---|
| 1. 대상 bin | `_bins` | `[floor_5min(until) - lookback, floor_5min(until))`. 끝난 bin만 처리. lookback이 5의 배수가 아니면 시작을 다음 5분 경계로 올림(예: until=08:00:30, lookback=7 → 07:55 bin 하나) |
| 2. 링크 | `_load_links` | 활성 구간의 본선(`is_mainline=1`) 링크. bin마다 `valid_from <= bin < valid_to`로 거름 |
| 3. 관측 | `_load_obs` | `link_id`로 대조, `ok`이고 `speed > 0`이며 `collected_at <= until`인 것 중 bin 안에서 가장 늦은 1건. `ok`인데 speed≤0이면 경고 로그 후 제외 |
| 4. 구간 값 | `_segment_value` | 거리 가중 조화평균 `Σlen / Σ(len/speed)` → `ok`/`partial`, 길이 NULL이 섞이면 단순 평균 `unweighted`, 관측 없으면 NULL `missing` |
| 5. 저장 | `_run` | `INSERT OR REPLACE`, `available_at` = 사용한 관측의 최대 `collected_at`(missing이면 bin 끝) |

## 왜 이렇게 하나

- **조화평균**: 구간을 지나는 통행시간 기준 평균 속도와 같다. 산술평균은 빠른 링크에 치우친다.
- **결측은 NULL**: 0 km/h는 "정체"로 읽히므로 관측 없음과 섞지 않는다. `default_value`·`out_of_range` 관측도 뺀다.
- **미래 정보 금지**: `collected_at > until`인 관측과 아직 끝나지 않은 bin은 쓰지 않는다. 예측 모델이 실시간과 같은 조건으로 학습되게 하기 위해서다.

## v0에서 아직 안 하는 것 (Slice 1)

- SPEC 6.2의 70% 부분 관측 기준(지금은 1개라도 관측되면 `partial`)
- SPEC 6.3 forward fill(`is_imputed`, `imputed`)
- 측도 링크 속도(`speed_side`), 교통량(`volume`)은 NULL

테스트: `tests/preprocessing/`
