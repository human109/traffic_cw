# preprocessing

링크 단위 원본 관측(`traffic_observation`)을 구간 x 5분 bin 값(`segment_traffic_5min`)으로 집계한다.
공개 진입점은 `preprocessing.run(until, conn=None, lookback_minutes=60) -> int` 하나다(C-06).

## 파일

- `aggregate.py` — 진입점 `run`과 DB 읽기·쓰기. 규칙 적용 순서와 저장만 담당한다.
- `rules.py` — 판정 규칙의 순수 함수(DB를 모른다). 단위 테스트는 `tests/preprocessing/test_rules.py`.

## 흐름 (`preprocessing/aggregate.py`)

| 단계 | 함수 | 내용 |
|---|---|---|
| 1. 대상 bin | `_bins` | `[floor_5min(until) - lookback, floor_5min(until))`. 끝난 bin만 처리. lookback이 5의 배수가 아니면 시작을 다음 5분 경계로 올림(예: until=08:00:30, lookback=7 → 07:55 bin 하나) |
| 2. 링크 | `_load_links` | 활성 구간의 링크를 본선(`is_mainline=1`)과 측도(0)로 나눠 둔다. bin마다 `valid_from <= bin < valid_to`로 거름 |
| 3. 관측 | `_load_obs` | `link_id`로 대조, `ok`이고 `speed > 0`이며 `collected_at <= until`인 것 중 bin 안에서 가장 늦은 1건. `ok`인데 speed≤0이면 경고 로그 후 제외. 갱신 정지 관측은 뺀다 |
| 3-1. 갱신 정지 | `_frozen_keys` + `rules.frozen_mask` | 링크별로 원본 시각(`source_timestamp`)이 서로 다른 관측을 시간순으로 볼 때 같은 speed가 `frozen_repeat_count`(6)회 이상 이어지면 6번째부터 제외. 판정을 위해 창보다 `frozen_repeat_count×5분` 더 앞의 관측까지 읽는다. 원본 시각이 같은 반복(다른 수집원이 같은 시각)은 1건으로 센다 |
| 4. 구간 값 | `rules.segment_speed` | 관측 길이 합 / 전체 길이 합 ≥ `partial_min_coverage`(0.7)일 때만 산출: 거리 가중 조화평균 `Σlen / Σ(len/speed)` → 전부면 `ok`, 아니면 `partial`. 미달이면 NULL `missing`. 길이를 모르는 링크가 섞이면 단순 평균 `unweighted`(커버리지는 링크 수 비율로 대체) |
| 4-1. 측도 | 4와 같은 규칙 | 측도 링크로 `speed_side`를 계산한다. 측도가 없거나 기준 미달이면 NULL. `quality_flag`에는 영향 없음 |
| 4-2. 짧은 결측 보정 | `rules.fill_source` | `missing`인 bin의 직전 연속 결측(그 bin 포함, `imputed`도 결측으로 센다)이 `ffill_max_bins`(2) 이하이고 그 앞 bin이 실제 값이면 그 값으로 채움 → `imputed`, `is_imputed=1`, `available_at`=bin 끝 |
| 5. 저장 | `_run` | `INSERT OR REPLACE`, `available_at` = 사용한 관측의 최대 `collected_at`(missing·imputed는 bin 끝) |

## 결측 보정의 두 가지 규칙 (브리프 결측 규칙 메모)

- **보정값은 근거가 되지 못한다**: `imputed` bin은 연속 결측 길이에 포함되고, 다음 결측 bin의 근거로 쓰지 않는다.
  그래서 4 bin 연속 결측이면 1·2번째만 채워지고 3번째부터 `missing`이다.
- **이미 채운 bin은 되돌리지 않는다**: 다시 집계했을 때 근거 bin이 사라졌거나 결측이 더 길어 보였더라도
  이미 기록한 `imputed` 행을 `missing`으로 되돌리지 않는다. 되돌리면 같은 시각 예측의 입력이 사후에
  바뀌어 재현이 깨진다. 같은 `until`로 다시 실행하면 항상 같은 결과다(멱등).

보정의 근거가 되는 "직전 실제 bin"은 이번 실행에서 계산한 값과 DB에 이미 있는 행(이전 실행 결과) 모두에서 찾는다.
창의 첫 bin도 DB의 직전 행을 본다.

주의: 과거 `until`로 다시 실행(백필)하면 창 앞쪽 bin의 "직전 행"은 그보다 나중에 실행이 쓴 값일 수 있다.
백필은 시간순(오래된 `until`부터)으로 실행한다.

## 왜 이렇게 하나

- **조화평균**: 구간을 지나는 통행시간 기준 평균 속도와 같다. 산술평균은 빠른 링크에 치우친다.
- **70% 기준**: 일부 링크만 관측된 값을 실제처럼 쓰면 혼잡 판단이 흔들린다. 미달이면 `missing`으로 남기고
  짧은 결측만 직전 값으로 채운다. 결측을 0으로 바꾸지 않는다(SPEC 4.5, 6.3).
- **갱신 정지**: 수집원이 같은 값을 반복해서 보내면(원본 시각만 바뀜) 실제 도로 상태가 아니라 결측이다.
  값이 아니라 **원본 시각이 바뀌는** 반복만 세므로, 같은 값이 계속 나와도 시각이 바뀌는 정상 데이터는 제외하지 않는다.
- **미래 정보 금지**: `collected_at > until`인 관측과 아직 끝나지 않은 bin, 결측 뒤 bin의 값은 쓰지 않는다.
  예측 모델이 실시간과 같은 조건으로 학습·평가되게 하기 위해서다.

## 아직 안 하는 것

- 교통량(`volume`)은 NULL (링크 교통량 수집 확보 후)
- SPEC 6.4 제한속도 기반 이상치 기준 (`max_valid_speed_kmh` 상식선만 적용 중)

테스트: `tests/preprocessing/`
