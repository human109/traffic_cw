# C-01 DB 스키마

| 항목 | 내용 |
|---|---|
| 상태 | frozen |
| 버전 | v1.1 |
| 영향 받는 에이전트 | 전체 |
| 계약 테스트 | `tests/contracts/test_c01_schema.py` |

## 정의

DDL 원문은 `docs/contracts/C-01-schema.sql`이다. `database/schema.sql`은 이 파일과 내용이 같아야 한다(주석·공백 제외 비교). 테이블 쓰기 소유권은 AGENTS.md 3장을 따른다.

## 불변 조건

- 모든 시각 컬럼은 `YYYY-MM-DDTHH:MM:SS+09:00` 문자열이다(`common.timeutil.to_iso`).
- 결측은 NULL로 저장한다. 수집 실패나 미관측을 0으로 쓰지 않는다.
- `segment_link.source`는 **링크 ID 체계의 출처**다(예: `moct_nodelink` = 국토부 표준노드링크, 테스트는 `synthetic`). 관측 수집원(`traffic_observation.source`, 예: `its`)과는 다르다. ITS와 경찰청 UTIC 모두 표준노드링크 ID를 쓰므로(R-01, R-02), 수집기와 전처리는 `link_id`로만 대조하고 `segment_link.source`로 거르지 않는다.
- `traffic_observation.quality_flag`: `ok` / `default_value`(API가 준 0 등 결측을 나타내는 값) / `out_of_range` / `frozen`(Slice 1)
- `segment_traffic_5min.quality_flag`:
  - `ok`: 본선 링크가 모두 관측되었고 길이가 모두 있어 거리 가중 조화평균으로 계산함
  - `partial`: 일부 링크만 관측됨(길이는 모두 있음)
  - `unweighted`: 관측 링크 중 길이를 모르는 링크가 있어 단순 평균으로 계산함
  - `missing`: 관측된 링크 없음, speed는 NULL
  - `imputed`: forward fill (Slice 1)
- `segment_traffic_5min.available_at`: 사용한 관측의 최대 `collected_at`. missing이면 bin 끝 시각.
- `traffic_prediction.input_quality`: `ok` / `degraded` / `skipped`(predicted_value NULL)
- `calendar_info`의 방학·휴가·연휴 인접 컬럼은 모르면 NULL이다(0은 "아님"이 확인된 경우만).

## 변경 이력

| 버전 | 일자 | 변경 | CR 출처 |
|---|---|---|---|
| v1.1 | 2026-11-18 | DDL 변경 없음. `segment_link.source`의 의미(링크 ID 체계 출처)를 명시 | Task 5 리뷰 I-1 |
| v1 | 2026-11-18 | SPEC 5장·20.6 DDL 확정. `IF NOT EXISTS` 추가, `segment_traffic_5min`에 `unweighted` 플래그, `calendar_info` 방학·휴가 컬럼 NULL 허용 | Slice 0 계획, R-05 |
