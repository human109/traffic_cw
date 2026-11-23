# C-02 수집 원본 레코드 형식

| 항목 | 내용 |
|---|---|
| 상태 | frozen |
| 버전 | v2.2 |
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

**저장 범위 (v2)**: 원본 응답 파일(`data/raw/`)은 응답 전체를 보관한다. `traffic_observation`에는 `roadName`이 `settings.its_store_road_names`에 속하거나(기본 `("창원대로",)`, 양방향 모두) `link_id`가 현재 유효한 대상 링크(`segment_link`)인 item만 저장한다(v2.1). 창원 bbox 응답(약 6,800개)을 모두 저장하면 하루 약 370MB가 쌓이기 때문이다. 다른 도로가 필요해지면 원본 파일에서 재적재한다.
- (v2.2) 기본 저장 도로는 `settings.corridors`와 같다(`("창원대로", "원이대로")`).
- (v2.2) **원본 재적재**(`collector.maintenance.reload_raw`, C-06 v2.3): 보관 중인 원본 `raw_dir/its/<YYYYMMDD>/<HHMMSS>.xml.gz`에서 지정 도로 item을 같은 파싱·quality_flag 규칙으로 `traffic_observation`에 넣는다. `collected_at`은 **원본 파일 이름의 수집 시각**(KST, 초 포함)이다 — 재적재를 실행한 시각을 쓰면 as-of 규칙(미래 정보 금지)이 깨진다. `raw_file`은 그 원본의 저장소 루트 기준 상대 경로, 이미 있는 (source, link_id, source_timestamp)는 건너뛴다. `collection_log`에는 쓰지 않는다.
- 거르는 위치는 수집기다(어댑터 `parse`는 계속 모든 item을 레코드로 만든다).
- `partial` 판정과 `links_received`는 지금처럼 대상 링크(`segment_link`) 기준이다.
- `record_count`는 실제로 새로 저장한 행 수다. 응답에 item은 있으나 저장 범위(도로명 또는 대상 링크)에 드는 item이 0개이면 `failed`("저장 대상 도로 item 없음")로 기록한다.

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
| v2.2 | 2026-11-23 | 저장 도로에 원이대로 추가(`= settings.corridors`), 원본 재적재 규칙(`collected_at` = 원본 파일 수집 시각) | 원이대로 W-00 |
| v2.1 | 2026-11-20 | 저장 범위에 대상 링크 포함(도로명 OR 대상 링크). `collected_at`은 응답 수신 시각(`run_once`의 `clock`). 새 행이 0인 회차(`no_update`)는 원본 파일을 남기지 않음 | Slice 0 최종 리뷰 I5·M1·M2 |
| v2 | 2026-11-19 | DB 저장 범위를 `its_store_road_names` 도로로 제한(원본 파일은 전체 보관). `ObservationRecord`에 `road_name` 필드 추가 | 첫 운영 저장량(1회 6,792행) |
| v1 | 2026-11-18 | ITS 매핑, quality_flag 판정 확정 | R-01, R-02 |
