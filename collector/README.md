# collector — 교통 데이터 수집

외부 API(현재 ITS 국가교통정보센터)를 한 번 조회해서 원본을 보관하고, 링크 단위 관측값을
`traffic_observation`에, 수집 1회의 결과를 `collection_log`에 기록한다. 이 두 테이블의 쓰기 소유자다.

## 흐름 (`run_once`)

1. `segment_link`에서 지금 유효한 대상 링크를 읽는다 (`runner._target_links`).
2. `adapter.fetch(now)`로 응답을 받는다. 연결 오류·5xx는 재시도, 401·403은 바로 인증 오류.
3. fetch가 끝난 시각을 `collected_at`으로 기록한다(`clock` 인자, 기본 실제 시각). 넘겨받은 `now`는
   `started_at`과 대상 링크 유효 판정에만 쓴다.
4. 응답 본문이 있으면 `data/raw/{source}/{YYYYMMDD}/{HHMMSS}.xml.gz`로 저장한다 (`store.save_raw`).
   상대 `raw_dir`은 저장소 루트 기준으로 해석한다(`database.db.connect`와 같은 규칙, `collector/paths.py`).
   `traffic_observation.raw_file`에는 기존 운영 행과 같은 루트 기준 상대 경로를 기록한다
   (`raw_dir`이 루트 밖 절대 경로면 절대 경로). 단 `no_update` 회차는 이번에 쓴 파일을 지워
   원본을 다시 쌓지 않는다(진단이 필요한 실패 회차는 둔다).
5. `adapter.parse`로 C-02 레코드를 만들고 `INSERT OR IGNORE`로 넣는다 (`store.insert_observations`).
6. 상태를 판정해 `collection_log`에 1행 남기고 commit한다. 예외는 밖으로 던지지 않는다.

| 상태 | 조건 |
|---|---|
| `auth_error` | HTTP 401·403, 키 미설정 |
| `failed` | 그 밖의 요청·파싱 실패 (레코드 0건) |
| `no_update` | 새로 들어간 행이 0건 (같은 `createdDate` 반복 조회) — 원본 파일을 새로 쓰지 않는다 |
| `partial` | 대상 링크 중 응답에 없는 것이 있음 (대상이 0개면 판정 안 함) |
| `success` | 그 밖 |

## 핵심 코드 위치

| 파일 | 내용 |
|---|---|
| `__init__.py` | 공개 진입점 `run_once` (C-06) |
| `runner.py` | 상태 판정, 연결·commit 관리 |
| `base.py` | `FetchResult`, `SourceAdapter` 프로토콜 — 수집원을 추가할 때 구현할 인터페이스 |
| `its.py` | ITS 요청 파라미터, tenacity 재시도, XML 파싱, `quality_flag` 판정, 키 가리기 |
| `store.py` | 원본 파일·관측·로그 저장 (commit하지 않음) |
| `maintenance.py` | 정비 도구 2가지(기본 dry-run, `--apply`로 실행). `purge --raw <gz>`: 저장 범위 밖 관측 행 정리+VACUUM. `--raw`에는 저장 범위 링크를 뽑을 최근 ITS 원본(예: `data/raw/its/<YYYYMMDD>/<HHMMSS>.xml.gz`)을 넘긴다. DB 백업은 자동이 아니므로 `--apply` 전에 수동 백업하고, `--apply` 시 대상 DB 절대 경로를 출력한다. `prune-raw`: `raw_keep_days`(기본 30일)보다 오래된 원본 날짜 폴더 정리. 날짜가 아닌 폴더·오늘·어제는 항상 보존하고, 한 폴더 삭제가 실패해도 나머지를 계속 지운다 |
| `scheduler.py` | 파이프라인 collect → preprocess → backfill → predict. `python -m collector.scheduler --once`로 1회, 인자 없이 상주(매 5분 30초, KST). 예정 시각보다 `scheduler_misfire_grace_s`(60초) 넘게 늦으면 그 회차는 건너뛴다. `--evaluate`로 평가 1회, `--maintenance`로 운영 작업 1회 실행. 상주 시 job 3개: 파이프라인, 평가(매일 `eval_cron_hour:eval_cron_minute`, 기본 10:05), 운영(매일 `backup_cron_hour`시, 기본 03:00 — DB 백업 후 원본 정리). `--once --evaluate`, `--once --maintenance` 조합에서 파이프라인에 실패 단계가 있으면 평가·운영 작업은 건너뛰어진다 |

## 파이프라인 as-of 시각 (D-COL-08)

`run_pipeline`은 collect 단계에는 스케줄 시각(예: 10:00:30)을, collect가 끝난 뒤 실행하는 단계
(preprocess·backfill·predict)에는 collect가 끝난 시각(예: 10:00:33)을 as-of로 넘긴다. collect가
관측에 기록하는 `collected_at`은 그 시각이므로, 같은 회차의 집계·예측이 as-of 규칙
(`collected_at`/`available_at ≤ until`/`now`)에서 방금 수집한 최신 bin을 놓치지 않는다.
collect가 실패해도 뒤 단계는 새 시각으로 실행된다(실패 격리 유지). 결과 로그에 두 시각을 함께
남긴다(`파이프라인 <now> (as-of <종료 시각>)`). 미래 정보 불변식은 그대로다 — as-of 시각에
실제로 도착해 있는 데이터만 쓴다.

## 주의

- 수집 실패를 0이나 빈 레코드로 저장하지 않는다. 빈 `speed`는 NULL, 0은 `default_value` 플래그로 남긴다.
- 저장 범위(C-02 v2 + 리뷰 M1): 원본 파일은 응답 전체를 보관하고, `traffic_observation`에는 `roadName`이
  `settings.its_store_road_names`(기본 `창원대로`)에 속하거나 **또는** 현재 유효한 대상 링크인 item만 넣는다.
  둘 다 아니면 `failed`("저장 대상 도로 item 없음").
- `resultCode=0`이어도 읽을 수 있는 item이 하나도 없으면 `failed`("응답에 읽을 수 있는 item 없음")다.
- 속도가 `NaN`이면 `out_of_range` 플래그를 붙이지만, sqlite는 REAL NaN을 NULL로 저장한다. 즉 DB에서는 `speed IS NULL`, `quality_flag='out_of_range'`로 보인다.
- 수집 중 예외가 나면 `run_once`는 호출자가 넘긴 연결도 rollback한다.
- 인증키는 URL 쿼리에 들어가므로 오류 메시지·로그에서 `mask_secret`으로 가린다.
- 테스트(`tests/collector/`)는 네트워크 없이 가짜 session·adapter와 `tests/fixtures/`의 합성 XML을 쓴다.
