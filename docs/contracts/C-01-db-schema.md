# C-01 DB 스키마

| 항목 | 내용 |
|---|---|
| 상태 | frozen |
| 버전 | v1.3 |
| 영향 받는 에이전트 | 전체 |
| 계약 테스트 | `tests/contracts/test_c01_schema.py` |

## 정의

DDL 원문은 `docs/contracts/C-01-schema.sql`이다. `database/schema.sql`은 이 파일과 내용이 같아야 한다(주석·공백 제외 비교). 테이블 쓰기 소유권은 AGENTS.md 3장을 따른다.

## 불변 조건

- 모든 시각 컬럼은 `YYYY-MM-DDTHH:MM:SS+09:00` 문자열이다(`common.timeutil.to_iso`).
- 결측은 NULL로 저장한다. 수집 실패나 미관측을 0으로 쓰지 않는다.
- `segment_link.source`는 **링크 ID 체계의 출처**다(예: `moct_nodelink` = 국토부 표준노드링크, 테스트는 `synthetic`). 관측 수집원(`traffic_observation.source`, 예: `its`)과는 다르다. ITS와 경찰청 UTIC 모두 표준노드링크 ID를 쓰므로(R-01, R-02), 수집기와 전처리는 `link_id`로만 대조하고 `segment_link.source`로 거르지 않는다. 단 ITS는 개정 이전 버전 ID를 줄 수 있으므로(R-06b: 2026-11-11 배포본에 없는 ID 4개), `segment_link.link_id`는 **수집 API가 실제로 주는 ID**로 두고 길이는 배포본 값을 쓴다(`config/build_segment_links.py`의 `ITS_ID_OVERRIDES`). 링크 ID를 바꿀 때는 기존 행의 `valid_to`를 닫고 새 행을 추가한다.
- `traffic_observation.quality_flag`: `ok` / `default_value`(API가 준 0 등 결측을 나타내는 값) / `out_of_range` / `frozen`(Slice 1)
- `segment_traffic_5min.quality_flag`:
  - `ok`: 본선 링크가 모두 관측되었고 길이가 모두 있어 거리 가중 조화평균으로 계산함
  - `partial`: 관측된 본선 길이 합이 전체 본선 길이의 `partial_min_coverage`(0.7) 이상이지만 전부는 아님
  - `unweighted`: 관측 링크 중 길이를 모르는 링크가 있어 단순 평균으로 계산함
  - `missing`: 관측 비율이 기준 미만이거나 관측 없음, speed는 NULL
  - `imputed`: 짧은 결측(연속 `ffill_max_bins` 이하)을 직전 실제 bin 값으로 채움. `is_imputed=1`, `available_at`=bin 끝. 보정값을 근거로 다시 보정하지 않으며, 한 번 채운 bin은 뒤에 결측이 길어져도 되돌리지 않는다.
- `segment_traffic_5min.speed_side`: 측도(`is_mainline=0`) 링크로 본선과 같은 규칙(조화평균·커버리지 기준)으로 계산한 속도. 기준 미달이면 NULL. `quality_flag`에 영향 없음.
- 갱신 정지(`frozen`): 원본 시각(`source_timestamp`)이 바뀌는 연속 관측에서 같은 speed가 `frozen_repeat_count`(6)회 이상 이어지면 6번째부터 집계에서 뺀다. `traffic_observation` 행은 고치지 않는다(쓰기 소유권). 원본 시각이 같은 반복은 해당하지 않는다.
- `segment_traffic_5min.available_at`: 사용한 관측의 최대 `collected_at`. missing이면 bin 끝 시각.
- `traffic_prediction.input_quality`: `ok` / `degraded` / `skipped`(predicted_value NULL)
- `calendar_info`의 방학·휴가·연휴 인접 컬럼은 모르면 NULL이다(0은 "아님"이 확인된 경우만).

## 변경 이력

| 버전 | 일자 | 변경 | CR 출처 |
|---|---|---|---|
| v1.3 | 2026-11-20 | 인덱스 `ix_pred_target_time` 추가(backfill·평가 기간 조회). `IF NOT EXISTS`라 운영 DB에 `init_db`로 안전하게 적용 | Slice 1 Task 4 리뷰 |
| v1.2 | 2026-11-19 | DDL 변경 없음. partial 70% 기준, imputed·speed_side·갱신 정지 규칙 정의 | Slice 1 계획 |
| v1.1 | 2026-11-18 | DDL 변경 없음. `segment_link.source`의 의미(링크 ID 체계 출처)를 명시 | Task 5 리뷰 I-1 |
| v1 | 2026-11-18 | SPEC 5장·20.6 DDL 확정. `IF NOT EXISTS` 추가, `segment_traffic_5min`에 `unweighted` 플래그, `calendar_info` 방학·휴가 컬럼 NULL 허용 | Slice 0 계획, R-05 |
