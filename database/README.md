# database

SQLite 연결과 스키마를 제공하는 공용 모듈이다. 다른 모듈은 여기 있는 두 함수로만 DB에 연결한다(C-06).

## 하는 일

| 무엇 | 어디 |
|---|---|
| 스키마(DDL). `docs/contracts/C-01-schema.sql`의 복사본이며 계약 테스트가 같은지 확인한다 | `database/schema.sql` |
| `connect(path=None, readonly=False)`: WAL, `foreign_keys=ON`, `row_factory=sqlite3.Row`. readonly는 `?mode=ro` URI | `database/db.py` |
| `init_db(conn)`: schema.sql 실행. 모두 `IF NOT EXISTS`라 재실행 안전 | `database/db.py` |
| 구간·링크 시드 UPSERT, `distance_m` 계산 | `scripts/load_segments.py` |
| 운영 DB 생성 + 시드 적재 (`python -m scripts.init_db`) | `scripts/init_db.py` |

## 알아 둘 점

- 스키마는 직접 고치지 않는다. 계약(C-01) 변경 요청 → 계약 SQL 갱신 → 여기에 복사 순서다.
- WAL 모드는 DB 파일에 기록되므로 쓰기 연결에서만 설정한다. readonly 연결은 기존 모드를 따른다.
- 링크 CSV의 빈 값은 NULL로 넣는다. 길이를 모르는 링크가 하나라도 있으면 구간 `distance_m`도 NULL이다(0이 아님).
- 시각은 모두 `YYYY-MM-DDTHH:MM:SS+09:00` 문자열로 저장한다(`common.timeutil`).

테스트: `tests/database/`
