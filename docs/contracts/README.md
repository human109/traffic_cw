# 인터페이스 계약

모듈 간 인터페이스를 정의한다. 규칙은 `AGENTS.md` 4장을 따른다. 계약 문서는 **오케스트레이터만** 수정하며, 다른 에이전트는 변경 요청(CR)을 제출한다.

## 계약 목록

| ID | 계약 | 근거 | 상태 | 버전 | 영향 받는 에이전트 | 선행 리서치 |
|---|---|---|---|---|---|---|
| C-01 | DB 스키마 | SPEC 5장 | draft | v0 | 전체 | R-03 |
| C-02 | 수집 원본 레코드 형식 | SPEC 4.3 | draft | v0 | dev-collector, dev-data | R-01, R-02 |
| C-03 | 전처리 출력과 특성 | SPEC 6장, 7.3 | draft | v0 | dev-data, dev-ml | - |
| C-04 | 예측 결과와 모델 등록 | SPEC 5.5~5.6, 7장 | draft | v0 | dev-ml, dev-dashboard, dev-publisher | - |
| C-05 | 공개 JSON | SPEC 20.3 | draft | v0 | dev-publisher | R-07 |
| C-06 | 모듈 공개 진입점 | SPEC 7.6 | draft | v0 | 전체 | - |

## 계약 문서 형식

```markdown
# C-xx <계약 이름>

| 항목 | 내용 |
|---|---|
| 상태 | draft / frozen / revising |
| 버전 | v1 |
| 영향 받는 에이전트 | ... |
| 계약 테스트 | tests/contracts/test_cxx_*.py |

## 정의
(테이블 DDL, 함수 시그니처와 docstring, JSON Schema 등. 모호함 없이)

## 불변 조건
(예: speed는 NULL 또는 0 이상, 시각은 +09:00 포함 ISO8601)

## 예시
(합성 예시는 synthetic 표시)

## 변경 이력
| 버전 | 일자 | 변경 | CR 출처 |
|---|---|---|---|
```

## C-06 진입점 초안 (참고)

W1에서 확정한다. 모듈은 아래 함수로만 서로를 호출한다.

| 모듈 | 진입점 | 역할 |
|---|---|---|
| database | `database.db.connect(path: str \| None = None) -> sqlite3.Connection` | WAL·FK 설정된 연결 |
| collector | `collector.run_once(now: datetime) -> CollectionResult` | 1회 수집 |
| preprocessing | `preprocessing.run(until: datetime) -> int` | `until`까지 신규 원본을 5분 집계, 처리 bin 수 반환 |
| preprocessing | `preprocessing.build_features(base_time: datetime, segment_ids: list[str] \| None = None) -> pandas.DataFrame` | as-of 특성 생성 |
| prediction | `prediction.predict_latest(base_time: datetime) -> int` | 활성·기준 모델 예측 저장, 저장 건수 반환 |
| prediction | `prediction.backfill_actuals(now: datetime) -> int` | 대상 시각이 지난 예측의 실제값·오차 갱신 |
| publisher | `publisher.publish(now: datetime) -> PublishResult` | (Phase 2) 공개 JSON 생성·업로드 |
