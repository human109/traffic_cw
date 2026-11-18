# dashboard — 내부 대시보드 v0

소유: `dev-dashboard`. 근거: SPEC 9.1~9.3. DB는 **읽기 전용**으로만 연다.

## 실행

저장소 루트에서:

```powershell
.venv\Scripts\streamlit run dashboard/app.py
```

DB 경로는 `config.settings.get_settings().db_path`(기본 `data/traffic.db`, 환경변수 `DB_PATH`)를 쓴다.

## 화면 구성

1. **상단**: 조회 시각, 최신 데이터 시각(속도가 있는 `segment_traffic_5min` bin의 `available_at` 최대값. `missing` bin은 제외).
   최신 데이터가 `stale_minutes`(10분) 이상 늦으면 `데이터 N분 지연` 경고, 집계가 없으면 `집계 데이터 없음` 경고.
2. **구간별 표**: 대상 구간(`is_target=1`)을 seq 순으로 보여준다.
   열: 구간, 이름, 현재 속도, 상태(원활/서행/정체, 속도 기준 파생값), 5·10·15·30분 후 예측.
   예측은 최신 bin의 `bin_time`을 `base_time`으로 하는 `baseline_persistence` 예측 중 `executed_at ≤ 조회 시각`인 것이다.
3. **최근 수집 결과**: `collection_log` 최근 10건.

화면은 60초마다 자동 갱신한다(`st.fragment(run_every=60)`).

## 표시 규칙

- 값이 없거나 예측이 `skipped`이면 `-`. 임의 수치·예시 값을 넣지 않는다.
- 혼잡 등급 경계는 `config/settings.py`의 `grade_free_min_kmh`, `grade_slow_min_kmh`(공개 화면과 같은 값).
- 숫자는 정수로 반올림해 표시한다.

## 코드 구조

- `data.py`: 조회·가공 순수 함수. `conn`을 인자로 받으므로 테스트에서 합성 DB를 넘긴다.
- `app.py`: Streamlit 화면. `database.db.connect(readonly=True)`로 연결한다.

테스트: `.venv\Scripts\python -m pytest tests/dashboard -q`
