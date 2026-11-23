# database

SQLite 연결과 스키마를 제공하는 공용 모듈이다. 다른 모듈은 여기 있는 두 함수로만 DB에 연결한다(C-06).

## 하는 일

| 무엇 | 어디 |
|---|---|
| 스키마(DDL). `docs/contracts/C-01-schema.sql`의 복사본이며 계약 테스트가 같은지 확인한다 | `database/schema.sql` |
| `connect(path=None, readonly=False, create=False)`: WAL, `foreign_keys=ON`, `row_factory=sqlite3.Row`. readonly는 `?mode=ro` URI. `create=True`는 `scripts/init_db.py`만 | `database/db.py` |
| `init_db(conn)`: schema.sql 실행 + C-01 v1.4 마이그레이션(1회성·원자적). 모두 재실행 안전 | `database/db.py` |
| 구간·링크 시드 UPSERT, `distance_m` 계산 | `scripts/load_segments.py` |
| 운영 DB 생성 + 시드 적재 (`python -m scripts.init_db`) | `scripts/init_db.py` |
| 날짜별 수집 성공률 조회(도로별): `python -m scripts.collection_rate [--days 7]` (readonly) | `scripts/collection_rate.py` |
| 운영 DB 온라인 백업·보관 정리: `python -m scripts.backup_db` | `scripts/backup_db.py` |
| CLI 표준출력 인코딩 방어(`make_stdout_lenient`): cp949 리디렉션에서도 `UnicodeEncodeError` 없이 출력 | `scripts/_console.py` |

## 알아 둘 점

- 스키마는 직접 고치지 않는다. 계약(C-01) 변경 요청 → 계약 SQL 갱신 → 여기에 복사 순서다.
- WAL 모드는 DB 파일에 기록되므로 쓰기 연결에서만 설정한다. readonly 연결은 기존 모드를 따른다.
- 링크 CSV의 빈 값은 NULL로 넣는다. 길이를 모르는 링크가 하나라도 있으면 구간 `distance_m`도 NULL이다(0이 아님).
- 시각은 모두 `YYYY-MM-DDTHH:MM:SS+09:00` 문자열로 저장한다(`common.timeutil`).
- **C-01 v1.4 마이그레이션(1회성·원자적)**: `CREATE TABLE IF NOT EXISTS`는 기존 테이블에 열을 더하지 않으므로, `init_db`는 `model_evaluation`에 `road_name` 열이 **없을 때만** `BEGIN IMMEDIATE` 트랜잭션 안에서 `ALTER TABLE ... ADD COLUMN road_name TEXT`로 더하고 v1.4 이전(NULL) 행을 `'창원대로'`로 채운다(그때까지 예측 대상 도로는 창원대로뿐). 실패하면 ROLLBACK 후 예외를 다시 던져 반쯤 적용된 상태가 남지 않는다. 열이 이미 있으면 아무것도 하지 않는다 — 나중에 생긴 `road_name` NULL 행은 건드리지 않으므로, 이후 모듈은 C-04 v1.4대로 도로를 항상 채워야 한다. 운영 DB 적용은 Task 5(운영 반영)에서 `python -m scripts.init_db`로 한다.
- **도로 구분(C-01 v1.4)**: 도로 키는 `road_segment.road_name`이다(`settings.corridors` 원소, ITS `roadName`과 같다). `seq`는 도로 안 순서이므로 `ORDER BY seq`만 쓰면 도로가 섞인다. 도로 순서는 `settings.corridors` 인덱스이고, 목록에 없는 도로는 그 뒤에 이름 순이다. `is_target=1`은 도로가 `settings.target_corridors`에 있고 참고 구간(S0·W0)이 아닌 구간이다.
- **도로별 수집 성공률(C-06 v2.3)**: `scripts.collection_rate.rate(conn, start_date, end_date, road_name=None)` — `road_name`을 주면 그 도로의 대상 구간(`is_target=1`·`is_active=1`)만 분모·분자로 세고, None이면 모든 대상 구간을 합산한다(`DayRate.road_name`은 None). 예측 대상이 아닌 도로는 `is_target=0`이라 어느 쪽에도 새지 않는다. `DayRate(date, road_name, is_service_day, expected, observed, rate)`다.
- **CLI 출력**: `python -m scripts.collection_rate --days N`은 대상 구간이 있는 도로마다 `[도로명] 대상 구간 k개` 제목의 날짜별 표와 `연속 service day ... >= rate_target(...)` 판정 줄을 `settings.corridors` 순서로 출력한다(대상 구간이 없는 도로는 표에서 뺀다). 전체 대상 구간이 없으면 표 대신 안내 문구 한 줄을 출력한다. rate를 판정할 수 없는 날(비 service day·expected 0)은 `-`다.
- `scripts/` CLI의 출력은 Windows PowerShell 리디렉션(`| Out-File`)·파이프에서 표준출력이 cp949(엄격)로 다시 열려도 죽지 않아야 한다. 출력 문자열에는 cp949에 없는 문자(em dash `—`, `≥` 등)를 쓰지 않고 ASCII(`-`, `>=`)로 쓰며, 각 `main()`은 `scripts/_console.make_stdout_lenient()`로 인코딩 오류를 대체 문자로 넘긴다(D-DAT-06).

테스트: `tests/database/`
