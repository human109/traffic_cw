# prediction

`segment_traffic_5min`(전처리 결과)을 읽어 구간 속도를 예측하고 `traffic_prediction`에 저장한다.
쓰기 소유 테이블: `traffic_prediction`, `model_registry`, `model_evaluation`.

## Slice 0: 현재 속도 유지(persistence) 기준 모델

- 각 대상 구간(`is_target=1`)에서 `available_at ≤ now`인 최신 bin의 속도를 horizon 5·10·15·30분 예측값으로 쓴다.
- 최신 bin이 없거나 `now - (bin 끝) > stale_minutes`(10분)이면 `skipped`, 예측값 NULL. 이때 base_time은 `floor_5min(now) - 5분`.
- bin 플래그 `ok`→`ok`, `partial`/`unweighted`→`degraded`, speed NULL→`skipped`.
- 대상 시각이 지나고 실제 bin이 들어오면 `backfill_actuals`가 `actual_value`, `abs_error`를 채운다.

## 코드 위치

| 무엇 | 어디 |
|---|---|
| 공개 진입점 `predict_latest`, `backfill_actuals` (C-06) | `prediction/__init__.py` |
| 최신 bin 선택(미래 정보 차단·오래된 입력 판정) | `prediction/baseline.py` `latest_usable_bin` |
| horizon별 저장, 품질 판정 | `prediction/baseline.py` `predict_segment` |
| 실제값 사후 갱신 | `prediction/baseline.py` `backfill` |
| 테스트 | `tests/prediction/test_persistence.py` |

최근 15분 평균, 과거 동일 시간대 평균 기준 모델과 평가(`model_evaluation`)는 이후 슬라이스에서 추가한다.
