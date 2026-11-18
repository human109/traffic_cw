# C-02 수집 원본 레코드 형식

| 항목 | 내용 |
|---|---|
| 상태 | frozen |
| 버전 | v1 |
| 영향 받는 에이전트 | dev-collector, dev-data |
| 계약 테스트 | `tests/contracts/test_fixtures.py` (픽스처가 이 형식을 따르는지) |

## 정의

수집기는 `common.records.ObservationRecord`를 만들어 `traffic_observation`에 저장한다. 필드는 SPEC 4.3을 따른다. 구간 ID와 방향은 저장하지 않고 `segment_link`로 결정한다.

### 수집원별 매핑

**ITS (`source="its"`, R-02)**: 응답 XML 구조는 `response > header(resultCode, resultMsg) > body > totalCount, items > item`이다.

| 응답 필드 | 레코드 필드 | 변환 |
|---|---|---|
| `linkId` | `link_id` | 문자열 그대로 |
| `speed` | `speed` | float(km/h). 빈 태그면 None |
| `travelTime` | `travel_time` | float(초). 빈 태그면 None |
| `createdDate` | `source_timestamp` | `common.timeutil.parse_compact_kst` |
| - | `volume`, `congestion_code` | 항상 None (제공하지 않음) |
| `header/resultCode` | - | `0`이 아니면 응답 전체를 실패로 본다 |

`roadName`, `startNodeId`, `endNodeId` 등 나머지 필드는 원본 파일에만 남는다.

**경찰청 UTIC (`source="police_utic"`)**: 응답 형식이 확인되지 않았다(R-01). 사람이 확인한 뒤 v2에서 추가한다.

### quality_flag 판정 (수집기가 저장할 때)

| 조건 | speed 저장값 | quality_flag |
|---|---|---|
| speed가 빈 값 | NULL | `ok` |
| speed == 0 | 0 | `default_value` (0이 결측인지 정지인지 확인 전까지, SPEC 6.4) |
| speed < 0 또는 speed > `settings.max_valid_speed_kmh` | 원값 | `out_of_range` |
| 그 밖의 경우 | 원값 | `ok` |

원본 값은 바꾸지 않고, 플래그만 붙인다. 집계는 `ok`이면서 speed NOT NULL인 행만 쓴다.

## 변경 이력

| 버전 | 일자 | 변경 | CR 출처 |
|---|---|---|---|
| v1 | 2026-11-18 | ITS 매핑, quality_flag 판정 확정 | R-01, R-02 |
