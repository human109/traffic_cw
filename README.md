# 창원대로 출근길 교통 흐름 예측 (학습 프로젝트)

창원대로(팔용사거리 → 성주광장, 창원터널 방면)의 링크별 속도를 ITS 국가교통정보센터 API로 수집하고, 구간(S1~S6)별 5·10·15·30분 후 속도를 예측한다.

| 문서 | 내용 |
|---|---|
| `PRD.md` | 무엇을, 왜 |
| `SPEC.md` | 기술 명세 (구간 정의는 3.3) |
| `AGENTS.md` | 에이전트 병렬 개발 규칙 |
| `docs/tasks/BOARD.md` | 작업 현황 |
| 모듈별 `README.md` | `collector/`, `database/`, `preprocessing/`, `prediction/`, `dashboard/` |

## 처음 한 번

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env          # .env 에 ITS_API_KEY 를 직접 입력한다 (Git에 올리지 않음)
.venv\Scripts\python scripts\init_db.py   # DB 생성 + 구간 7개·링크 표 적재 (수집 전에 반드시 실행)
.venv\Scripts\python -m pytest            # 테스트
```

## 실행

| 명령 | 하는 일 |
|---|---|
| `.\run_collector.ps1 --once` | 수집 → 5분 집계 → 실제값 갱신 → 예측을 1회 실행 |
| `.\run_collector.ps1` | 상주 실행(Ctrl+C로 종료). job 3개: 5분마다(xx:x0:30, xx:x5:30) 위 과정, 매일 10:05 평가, 매일 03:00 운영(DB 백업 → 원본 정리) |
| `.\run_collector.ps1 --evaluate` | 평가(`prediction.evaluate`)만 1회. `--once`와 함께 쓰면 파이프라인에 실패 단계가 있을 때 평가를 건너뜀 |
| `.\run_collector.ps1 --maintenance` | 운영 작업(DB 백업 → 원본 정리)만 1회 |
| `.\run_dashboard.ps1` | 내부 대시보드 (http://localhost:8501, 이 PC에서만) |

코드나 설정(`config/settings.py`)을 바꾸면 상주 수집기를 재시작해야 반영된다. 대시보드는 새로고침이면 된다.

## 운영 점검

| 명령 | 하는 일 |
|---|---|
| `.venv\Scripts\python -m scripts.collection_rate --days 7` | 날짜별 수집 성공률(평일·비공휴일 06:00~10:00, 목표 95%)과 "연속 service day 3일 이상 달성" 판정. 읽기 전용 |
| `.venv\Scripts\python -m scripts.backup_db` | DB 온라인 백업 → `data/backup/traffic_YYYYMMDD.db`. 14일 지난 같은 이름 형식만 삭제(수동 백업은 보존) |
| `.venv\Scripts\python -m collector.maintenance prune-raw [--apply]` | 30일 지난 원본 응답 폴더(`data/raw/<source>/<YYYYMMDD>`) 정리. 기본은 대상만 표시, 오늘·어제는 항상 보존 |

보관 기간·시각·목표값은 `config/settings.py`의 운영 절(`backup_keep_days`, `raw_keep_days`, `backup_cron_hour`, `eval_cron_hour/minute`, `rate_*`)에 있다.

## 상시 수집 (Windows)

1. 작업 스케줄러 → 기본 작업 만들기 → 트리거 "로그온할 때" → 동작 "프로그램 시작"
   - 프로그램: `powershell.exe`
   - 인수: `-NoProfile -ExecutionPolicy Bypass -File "<저장소 경로>\run_collector.ps1"`
   - 속성 → 설정: "작업이 실패하면 다시 시작" 1분 간격, "이미 실행 중이면 새 인스턴스 실행 안 함"
2. 전원 옵션 → 절전 "안 함", Windows 업데이트 사용 시간 설정에 06:00~10:00 포함
3. 확인: `logs/app.log`, 대시보드 하단 "최근 수집 결과"

## 링크 표 다시 만들기

표준노드링크 배포본이 바뀌면 R-03b 절차로 `docs/research/samples/`의 링크 표를 갱신한 뒤:

```powershell
.venv\Scripts\python -m config.build_segment_links   # 분할 링크를 ITS 링크 단위로 합쳐 config/segment_links.csv 생성
.venv\Scripts\python scripts\init_db.py
```
