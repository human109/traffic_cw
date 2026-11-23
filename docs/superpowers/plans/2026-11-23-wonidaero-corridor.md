# 원이대로 예측 대상 확장 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 원이대로(명곡교 → 가음정사거리) 구간 W0~W5를 창원대로와 같은 방식으로 수집·집계·예측·평가하고, 수집 성공률·평가·대시보드를 도로별로 본다.

**Architecture:** 도로 구분 키는 이미 있는 `road_segment.road_name`을 쓴다(설계의 `corridor` 열 대신 — 같은 역할, 마이그레이션 없음). 도로 목록·순서는 `settings.corridors`, 예측 대상 도로는 `settings.target_corridors`. 평가 도로 집계는 `model_evaluation`에 nullable `road_name` 열을 더해 구분한다. 원이대로 과거 관측은 보관 중인 원본 gz에서 재적재한다.

**Tech Stack:** Python 3.11, SQLite, APScheduler, Streamlit 1.67, plotly 7.1, pytest.

**Spec:** `docs/superpowers/specs/2026-11-23-wonidaero-corridor-design.md`, 근거 `docs/research/R-09-wonidaero-links.md`

**Task 0 결정 (W-01):** 모듈은 `target_corridors`를 직접 읽지 않는다 — `is_target`이 시드 시점에 이를 반영하므로 모듈은 지금처럼 `is_target=1`로만 거른다. 도로 순서만 `settings.corridors`를 쓴다(목록에 없는 도로는 뒤에 `road_name` 순). 픽스처: `fixture_db_two`/`fixture_conn_two`(`ROAD_A`=합성도로 S0~S3, `ROAD_B`=합성도로B W0~W2), `build_fixture_db(path, second_road=True, second_road_target=False)`.

## Global Constraints

- 도로 이름 문자열은 정확히 `창원대로`, `원이대로`(ITS `roadName` 값과 같음).
- `settings.corridors = ("창원대로", "원이대로")` — 표시·정렬 순서. `settings.its_store_road_names`는 이 값을 쓴다.
- `settings.target_corridors = ("창원대로",)` — 11/24 Slice 0 판정 전까지. 판정 후 Task 5에서 `("창원대로", "원이대로")`.
- 구간 ID `W0`(참고, `is_target=0`) `W1`~`W5`. 링크 표 = `docs/research/samples/wonidaero_segment_links_candidates_2026-11-23.csv`(35행, `valid_from=2026-11-24T00:00:00+09:00`).
- 구간 순서는 항상 (도로 순서 = `settings.corridors` 인덱스, `seq`). `ORDER BY seq`만 쓰면 S·W가 섞인다.
- 창원대로의 기존 수치(성공률, 평가 행)는 바뀌지 않아야 한다(설계 실패 조건).
- 불변식: 결측≠0, 미래 정보 금지(재적재 관측의 `collected_at`은 **원래 수집 시각**), KST, 운영 DB는 Task 5 전까지 읽기 전용.
- 모든 dev 작업은 모듈 README 갱신 포함(AGENTS.md 9장 4항).

## Review Focus

1. 재적재 관측의 `collected_at`을 재적재 실행 시각으로 넣으면 과거 집계가 전부 "아직 도착 안 함"이 되거나 as-of가 깨진다 → 원본 파일 이름의 수집 시각을 써야 한다 (Task 2 테스트).
2. 재적재를 두 번 실행하면 중복 행 → `UNIQUE(source, link_id, source_timestamp)`로 무시, 반환 수 0 (Task 2 테스트).
3. 원이대로가 `target_corridors`에 없을 때 W 구간이 성공률 분모·예측·대시보드에 새어 들어오면 창원대로 판정이 바뀐다 (Task 1·3·4 테스트).
4. 평가 집계 행에서 두 도로가 합쳐지면 창원대로 성적이 바뀐다 → 도로별 행, 기존 행은 `road_name='창원대로'`로 이전 (Task 1·3 테스트).
5. 대시보드에서 `?road=` 값이 잘못되거나 선택 도로에 구간이 없을 때 → 기본 도로·'-' 표시, 예외 없음 (Task 4 테스트).

---

### Task 0: 계약·설정·픽스처 (orchestrator)

**Files:** `docs/contracts/C-01-db-schema.md`, `C-01-schema.sql`, `C-02-observation.md`, `C-04-prediction.md`, `C-06-entrypoints.md`, `SPEC.md`(3.1, 3.3, 3.4), `config/settings.py`, `config/segments.py`, `config/segment_links.csv`, `tests/fixtures/`, `tests/contracts/`

- [ ] C-01 v1.4: `model_evaluation.road_name TEXT`(nullable, 집계 행의 도로). `road_segment.road_name` = 도로 구분 키, 정렬 규칙 명시. 운영 DB 적용은 `init_db`의 마이그레이션(`ALTER TABLE ... ADD COLUMN`, 기존 행 `'창원대로'`).
- [ ] C-02 v2.2: 저장 범위 = `settings.corridors`. 재적재 관측의 `collected_at` = 원본 파일 수집 시각.
- [ ] C-04 v1.4: 평가 집계 키 `(model_version, horizon, segment_id[NULL=도로 전체], road_name, regime)`. 구간 행도 `road_name`을 채운다.
- [ ] C-06 v2.3: `scripts.collection_rate.rate(conn, start_date, end_date, road_name: str | None = None)`(None = `target_corridors` 전체, `DayRate`에 `road_name` 필드 추가), `collector.maintenance.reload_raw(start: date, end: date, road_names: Sequence[str], conn=None, settings=None, *, dry_run=True) -> int`.
- [ ] SPEC 3.1·3.3 원이대로 표(R-09 SPEC 변경 제안 그대로, W3 로터리 갭 명기), 3.4 방향 문구를 도로별로.
- [ ] settings: `corridors`, `target_corridors`, `its_store_road_names = corridors`. segments.py: 원이대로 `_BOUNDS`(R-09 표), `direction="명곡교→가음정사거리 방면"`, `is_target = 1 if road in target_corridors and sid not in ("S0","W0") else 0`. segment_links.csv에 후보 35행 추가.
- [ ] 픽스처: 합성 DB에 W0~W2(원이대로) 구간·링크·관측 추가(`synthetic` 표시), `target_corridors`를 두 도로로 바꿀 수 있는 헬퍼.
- [ ] 계약 테스트 갱신, 전체 테스트 실행(하류 실패 목록이 Task 1~4 범위와 일치하는지 확인), 커밋 `[W-01] 원이대로 계약·설정·픽스처`.

### Task 1: dev-data — 마이그레이션, 도로별 성공률

**Files:** `database/schema.sql`, `database/db.py`(또는 `scripts/init_db.py`), `scripts/collection_rate.py`, `tests/database/`, `database/README.md`
**Consumes:** Task 0 계약·설정. **Produces:** `rate(..., road_name=None) -> list[DayRate]`(`DayRate(date, road_name, is_service_day, expected, observed, rate)`), `model_evaluation.road_name` 열.

- [ ] 실패 테스트: (a) 구 스키마(열 없음) DB에 `init_db` → 열 생김, 기존 행 `road_name='창원대로'`, 두 번 실행해도 동일; (b) `rate(..., road_name="창원대로")`가 W 구간을 세지 않음(창원대로 6구간 × 48 = 288); (c) `road_name=None`이고 `target_corridors=("창원대로",)`이면 W 제외; 두 도로면 도로별이 아니라 합산 분모 = 11×48; (d) CLI가 도로별 표를 출력, Slice 0 판정 줄은 창원대로 기준.
- [ ] 구현, 테스트 통과(`pytest tests/database tests/contracts -q`), README.

### Task 2: dev-collector — 원본 재적재

**Files:** `collector/maintenance.py`, `tests/collector/test_maintenance.py`, `collector/README.md`
**Produces:** `reload_raw(start, end, road_names, conn=None, settings=None, *, dry_run=True) -> int`, CLI `python -m collector.maintenance reload-raw --from YYYY-MM-DD --to YYYY-MM-DD --road 원이대로 [--apply]`.

- [ ] 실패 테스트(tmp raw + 합성 DB): 원본 2개 파일(`<date>/<HHMMSS>.xml.gz`) → 지정 도로 item만 삽입, `collected_at` = 파일 날짜·시각(KST) + 초는 파일명 그대로, `raw_file` 루트 기준 상대, 다른 도로 행 없음; 두 번째 실행 0; dry-run 무삽입·예정 수 반환; 깨진 gz는 경고 후 건너뜀; `collection_log`에 쓰지 않음.
- [ ] 구현은 기존 ITS 파서(`collector/its.py`의 item 파싱)를 재사용, `INSERT OR IGNORE`, 한 트랜잭션. 통과(`pytest tests/collector -q`), README.

### Task 3: dev-ml — 도로별 평가, 구간 순서

**Files:** `prediction/baseline.py`, `prediction/evaluate.py`, `tests/prediction/`, `prediction/README.md`
**Consumes:** `model_evaluation.road_name`(Task 1 스키마 — 테스트는 픽스처 DDL).

- [ ] 실패 테스트: 두 도로가 대상인 픽스처에서 `evaluate` → 집계 행이 도로마다 따로(`segment_id IS NULL`, `road_name` 각각), 구간 행도 `road_name` 채움; 창원대로 집계 수치가 원이대로 추가 전후 같음; `target_corridors=("창원대로",)`이면 W 예측 없음; 예측 대상 순서가 (도로 순서, seq).
- [ ] 구현, 통과(`pytest tests/prediction tests/integration -q`), README.

### Task 4: dev-dashboard — 도로 선택

**Files:** `dashboard/app.py`, `dashboard/data.py`, `tests/dashboard/`, `dashboard/README.md`
**Consumes:** `rate(..., road_name)`, `model_evaluation.road_name`, `settings.corridors/target_corridors`.

- [ ] 실패 테스트: `parse_nav`가 `road`도 다룸(잘못된 값 → 첫 대상 도로); 현재 표·시계열 구간 목록·히트맵·성공률·성능이 선택 도로만; 대상 도로가 하나면 선택 컨트롤 숨김; 제목에서 '창원대로' 고정 문구 제거; 합성 DB AppTest로 `?road=원이대로&view=시계열&seg=W2` 예외 없음.
- [ ] 구현, 통과(`pytest tests/dashboard -q`), README. 커밋 전 오케스트레이터가 운영 DB AppTest.

### Task 5: 운영 반영 (orchestrator + 사람, 11/24 판정 후)

- [ ] `python -m scripts.backup_db` → 백업 확인.
- [ ] `scripts/init_db.py`(마이그레이션 + W 구간·링크 적재, `target_corridors`는 아직 창원대로만).
- [ ] `python -m collector.maintenance reload-raw --from 2026-11-19 --to 2026-11-24 --road 원이대로` dry-run → 수 확인 → `--apply`.
- [ ] W 구간 재집계(`docs/ops/2026-11-20-reaggregate-slice1.py` 방식, 11/19~).
- [ ] `target_corridors`에 원이대로 추가 → `init_db` → 수집기 재시작(사람) → 다음 회차에서 W 예측 행·대시보드 확인, 성공률 `--days 2`.
- [ ] BOARD 갱신, 커밋 `[W-05] 원이대로 운영 반영`.

Tasks 1~4는 Task 0 뒤 병렬. 링크 `valid_from=2026-11-24`라 재적재·재집계 범위가 11/19부터면 링크 유효 기간 밖이 된다 → Task 0에서 W 링크 `valid_from`을 `2026-11-19T00:00:00+09:00`으로 정한다(2026-11-11 배포본 기준이고 그 사이 변경 없음).
