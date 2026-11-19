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
| `.\run_collector.ps1` | 위 과정을 5분마다(xx:x0:30, xx:x5:30) 상주 실행. Ctrl+C로 종료 |
| `.\run_dashboard.ps1` | 내부 대시보드 (http://localhost:8501, 이 PC에서만) |

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
