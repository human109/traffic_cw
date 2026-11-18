# 창원대로 출근길 교통 흐름 예측 (학습 프로젝트)

창원대로(팔용사거리 → 성주광장, 창원터널 방면)의 링크별 속도를 수집하고, 5·10·15·30분 후 구간 속도를 예측한다.

| 문서 | 내용 |
|---|---|
| `PRD.md` | 무엇을, 왜 |
| `SPEC.md` | 기술 명세 |
| `AGENTS.md` | 에이전트 병렬 개발 규칙 |
| `docs/tasks/BOARD.md` | 작업 현황 |

## 준비

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env   # .env 에 API 키를 직접 입력한다 (Git에 올리지 않음)
.venv\Scripts\python -m pytest
```

실행 방법(수집기, 대시보드)은 Slice 0 완료 시 추가한다.
