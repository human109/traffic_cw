# collector — 교통 데이터 수집

외부 API(현재 ITS 국가교통정보센터)를 한 번 조회해서 원본을 보관하고, 링크 단위 관측값을
`traffic_observation`에, 수집 1회의 결과를 `collection_log`에 기록한다. 이 두 테이블의 쓰기 소유자다.

## 흐름 (`run_once`)

1. `segment_link`에서 지금 유효한 대상 링크를 읽는다 (`runner._target_links`).
2. `adapter.fetch(now)`로 응답을 받는다. 연결 오류·5xx는 재시도, 401·403은 바로 인증 오류.
3. fetch가 끝난 시각을 `collected_at`으로 기록한다(`clock` 인자, 기본 실제 시각). 넘겨받은 `now`는
   `started_at`과 대상 링크 유효 판정에만 쓴다.
4. 응답 본문이 있으면 `data/raw/{source}/{YYYYMMDD}/{HHMMSS}.xml.gz`로 저장한다 (`store.save_raw`).
   단 `no_update` 회차는 이번에 쓴 파일을 지워 원본을 다시 쌓지 않는다(진단이 필요한 실패 회차는 둔다).
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
| `maintenance.py` | 저장 범위 밖 관측 행 정리. `python -m collector.maintenance purge --raw <gz>`(dry-run), `--apply`로 삭제+VACUUM. 백업 후 실행 |
| `scheduler.py` | 파이프라인 collect → preprocess → backfill → predict. `python -m collector.scheduler --once`로 1회, 인자 없이 상주(매 5분 30초, KST). 예정 시각보다 `scheduler_misfire_grace_s`(60초) 넘게 늦으면 그 회차는 건너뛴다. `--evaluate`로 평가(`prediction.evaluate`) 1회 실행. 상주 시 두 번째 job으로 매일 10:05:00 KST에 최근 7일 평가 |

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
