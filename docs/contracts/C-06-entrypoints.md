# C-06 모듈 공개 진입점

| 항목 | 내용 |
|---|---|
| 상태 | frozen |
| 버전 | v2 |
| 영향 받는 에이전트 | 전체 |
| 계약 테스트 | 각 모듈 테스트 + `tests/integration/` |

## 정의

모듈은 아래 함수로만 서로를 호출한다. 내부 함수를 import하지 않는다.

| 모듈 | 시그니처 | 동작 |
|---|---|---|
| database | `database.db.connect(path: str \| Path \| None = None, readonly: bool = False) -> sqlite3.Connection` | WAL, `foreign_keys=ON`, `row_factory=sqlite3.Row`. `readonly`이면 `file:...?mode=ro` URI. `path=None`이면 `get_settings().db_path` |
| database | `database.db.init_db(conn: sqlite3.Connection) -> None` | `database/schema.sql` 실행(재실행 안전) |
| collector | `collector.run_once(now: datetime, conn: sqlite3.Connection \| None = None, adapter: SourceAdapter \| None = None) -> CollectionResult` | 수집 1회. 예외를 밖으로 던지지 않고 항상 `collection_log`를 남긴다 |
| preprocessing | `preprocessing.run(until: datetime, conn: sqlite3.Connection \| None = None, lookback_minutes: int = 60) -> int` | `until` 이전에 끝난 bin을 집계해 `segment_traffic_5min`에 기록하고 행 수 반환 |
| prediction | `prediction.predict_latest(now: datetime, conn: sqlite3.Connection \| None = None) -> int` | 예측을 저장하고 저장 건수 반환 |
| prediction | `prediction.backfill_actuals(now: datetime, conn: sqlite3.Connection \| None = None) -> int` | 대상 시각이 지난 예측의 실제값·오차를 갱신하고 갱신 건수 반환 |
| prediction | `prediction.evaluate(now: datetime, conn: sqlite3.Connection \| None = None, days: int = 7) -> int` | (v2) C-04 평가 행을 `model_evaluation`에 저장하고 행 수 반환 |
| scripts | `scripts.load_calendar.load(conn: sqlite3.Connection, years: list[int]) -> int` | (v2) `calendar_info` UPSERT, 행 수 반환 |
| database | `database.db.connect(..., create: bool = False)` | (v2) 상대 경로는 저장소 루트 기준. 쓰기 연결에서 DB 파일이 없고 `create=False`면 `FileNotFoundError`. `scripts/init_db.py`만 `create=True` |

## 불변 조건

- `now`·`until`이 timezone 정보가 없는 datetime이면 `ValueError`를 낸다.
- `conn=None`이면 `database.db.connect()`로 연결하고 함수가 끝날 때 닫는다. `conn`을 받으면 닫지 않는다.
- 쓰기를 하는 진입점은 함수 안에서 commit한다.

## 변경 이력

| 버전 | 일자 | 변경 | CR 출처 |
|---|---|---|---|
| v2 | 2026-11-19 | `prediction.evaluate`, `scripts.load_calendar.load`, `connect(create=)` 추가 | Slice 1 계획, Slice 0 최종 리뷰 M3 |
| v1 | 2026-11-18 | Slice 0 진입점 확정 | Slice 0 계획 |
