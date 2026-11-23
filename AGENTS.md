# AGENTS.md — Agentic 개발 원칙

이 문서는 이 저장소에서 작업하는 **모든 AI 에이전트와 사람**이 따라야 하는 규칙이다. OpenCode는 이 파일을 모든 에이전트의 지침으로 자동으로 불러온다.

| 문서 | 역할 |
|---|---|
| `PRD.md` | 무엇을, 왜 만드는가 |
| `SPEC.md` | 어떻게 만드는가 (기술 명세, 단일 기준) |
| `AGENTS.md` (이 문서) | 누가, 어떤 순서와 규칙으로 만드는가 |
| `docs/contracts/` | 모듈 간 인터페이스 계약 |
| `docs/research/` | 리서치 결과 |
| `docs/tasks/BOARD.md` | 작업 현황판 |
| `.opencode/agents/` | 에이전트별 역할·권한 정의 |

---

# 1. 핵심 원칙

1. **계약 우선 (Contract-first)**
   모듈 간 인터페이스(DB 테이블, 함수 시그니처, JSON 형식)를 `docs/contracts/`에 먼저 확정한 뒤 구현을 시작한다. 계약이 확정되면 각 모듈은 다른 모듈의 완성을 기다리지 않고 병렬로 개발한다.

2. **소유권 분리 (Single owner per path)**
   모든 디렉터리에는 소유 에이전트가 정확히 하나 있다(2장). 에이전트는 자기 소유 경로만 수정한다. 이 규칙은 `.opencode/agents/`의 권한 설정으로 강제된다. 다른 모듈의 변경이 필요하면 직접 고치지 않고 요청한다(5.3).

3. **리서치와 구현의 분리**
   외부 사실(API 스키마, 링크 ID, 이용약관 등)의 조사는 `researcher`가 맡아 출처와 함께 `docs/research/`에 기록한다. 개발 에이전트는 확인되지 않은 외부 사실을 추측해서 코드에 넣지 않는다.

4. **DB를 통한 느슨한 결합**
   모듈은 서로의 내부 코드를 import하지 않는다. 데이터는 SQLite 테이블(계약 C-01)로 주고받고, 실행은 공개 진입점(계약 C-06)으로만 호출한다.

5. **픽스처로 병렬화**
   상류 모듈이 완성되지 않아도 하류 모듈은 공용 픽스처(`tests/fixtures/`)로 개발·테스트한다. 픽스처는 계약을 따르며 오케스트레이터가 관리한다.

6. **작은 작업, 명확한 완료 기준**
   작업 하나는 에이전트 하나가 한 세션에서 끝낼 수 있는 크기로 쪼갠다. 모든 작업에는 소유자, 선행 작업, 관련 계약, 완료 기준이 있다.

7. **증거 기반 보고**
   "완료"는 테스트 결과와 함께 보고한다. 실패, 건너뛴 항목, 추측한 부분은 숨기지 않고 보고한다.

---

# 2. 에이전트 역할과 소유권

| 에이전트 | 모드 | 모델 | 역할 | 수정 가능 경로 (소유) |
|---|---|---|---|---|
| `orchestrator` | primary | `claude-agent/opus#high` | 작업 분해·배정, 계약 관리, 통합, 커밋, 문서 갱신 | `docs/**`, `config/**`, `common/**`, `tests/fixtures/**`, `tests/contracts/**`, `tests/integration/**`, `tests/common/**`, `tests/conftest.py`, 루트 문서(`*.md`), 루트 실행 스크립트(`run_*.ps1`), `pyproject.toml`, `requirements*.txt`, `.gitignore`, `.env.example` |
| `researcher` | subagent | `opencode/beam-free#high` | 외부 사실 조사, 출처 기록, SPEC 변경 제안 | `docs/research/**` |
| `dev-collector` | subagent | `opencode/hy4-flash-free#high` | 수집기, 스케줄러 | `collector/**`, `tests/collector/**` |
| `dev-data` | subagent | `opencode/deepseek-v4.1-flash-free#high` | DB 스키마·저장소, 전처리, DB 스크립트 | `database/**`, `preprocessing/**`, `scripts/**`, `tests/database/**`, `tests/preprocessing/**` |
| `dev-ml` | subagent | `opencode/deepseek-v4.1-flash-free#max` | 기준 모델, 학습, 예측, 평가 | `prediction/**`, `notebooks/**`, `tests/prediction/**` |
| `dev-dashboard` | subagent | `opencode/flint-40b-free#high` | 내부 Streamlit 대시보드 | `dashboard/**`, `tests/dashboard/**` |
| `dev-publisher` | subagent | `opencode/mimo-v2.6-flash-free` | (Phase 2) 공개 JSON 발행, 시민 공개 웹 | `publisher/**`, `web/**`, `tests/publisher/**` |
| `reviewer` | subagent | `opencode/deepseek-v4.1-flash-free#max` | 계약 준수·프로젝트 불변식 검토 (읽기 전용) | 없음 |

모델은 `.opencode/agents/<에이전트>.md`의 frontmatter `model`에 정의되어 있다. 이 표는 그 설정의 문서상 기준이며, 모델을 바꾸면 **설정 파일과 이 표를 함께** 갱신한다.

### 모델 선정 이유

**공통 원칙**

- **오케스트레이터만 유료 Claude, 서브에이전트는 전부 무료 `opencode` 모델**이다. 오케스트레이터가 병렬로 4~5개 서브에이전트를 띄우는 구조라, 병렬 비용의 대부분을 차지하는 서브에이전트를 무료 모델로 두어야 전체 비용이 오케스트레이터 한 곳에만 발생한다.
- `#variant`는 추론 강도다(`low` … `max`). **결과 정확도가 곧 작업 성공 여부를 좌우하는 곳은 `max`/`high`**, 단순·반복 작업은 낮은 강도나 variant 없는 모델을 쓴다.
- 동시 실행 시 같은 무료 모델에 요청이 몰리면 rate limit에 걸리기 쉬우므로, 병렬 그룹의 모델을 의도적으로 분산했다.
- 무료 모델은 예고 없이 폐기되거나 제한될 수 있다. 각 에이전트의 **제한 시 대체 모델은 `.opencode/agents/orchestrator.md`의 "모델 제한 시 대체 모델" 절**에 있고, 오케스트레이터가 `subagent` 도구의 `model` 파라미터로 재배정한다. (OpenCode V2에는 에이전트별 자동 fallback 기능이 없다.)

**에이전트별**

- `orchestrator` — `claude-agent/opus#high`: 작업 분해, 계약 해석, 통합 판단, 커밋은 **오판 시 되돌리는 비용이 가장 큰** 의사결정이다. 하위 모델이 계약을 잘못 해석하거나 소유권을 침범하면 전체 슬라이스가 흔들리므로, 최상위 추론 모델을 쓰고 variant는 `high`로 둔다(최대 추론 `max`는 지연이 커서 대화형 조율에 불리).
- `reviewer` — `opencode/deepseek-v4.1-flash-free#max`: 코드 판독과 불변식 위반 판단은 **출력물 생성이 아니라 추론**이 핵심이다. 대화형 응답이 아니므로 강도를 `max`로 올려 오탐·누락을 줄인다. 코딩 계열 모델이라 코드 문맥 해석이 안정적이다.
- `researcher` — `opencode/beam-free#high`: 웹 문서와 API 스키마를 길게 읽고 요약해야 해 **1M 토큰 컨텍스트**가 유리하고, 학습에는 쓰지 않아 리서치 프롬프트에 외부 자료를 넣어도 보존 위험이 낮다(30일 보관). `webfetch`·`websearch`를 반복 호출하므로 **tool strict 지원** 모델을 골랐고, 사실·추론 구분 같은 판단이 들어가므로 variant는 `high`로 추론 여력을 준다. (구 모델 `opencode/longcat-2.5-free`는 2026-11-23 카탈로그에서 삭제되어 교체했다.) 한도·429로 실패하면 `nvidia/z-ai/glm-5.3-flash#thinking`로 대체한다.
- `dev-data` — `opencode/deepseek-v4.1-flash-free#high`: SQL 집계, 70% 관측 규칙, forward fill, as-of 조인처럼 **규칙을 정확히 구현**해야 하고 오류가 조용히 데이터를 오염시킨다. 구현 정확도 우선으로 `high`를 쓴다.
- `dev-ml` — `opencode/deepseek-v4.1-flash-free#max`: 수식·학습 파이프라인·walk-forward 평가는 **논리 오류의 발견 비용이 가장 큰** 영역이다. dev-data와 같은 계열을 쓰되 강도를 `max`로 올려, 모델 종류를 늘리지 않고 추론 여력을 확보한다.
- `dev-collector` — `opencode/hy4-flash-free#high`: 외부 API 어댑터·재시도·로깅은 패턴이 반복되는 작업이라 고속 모델로 충분하고, 수집은 주기적으로 자주 실행되므로 응답 속도가 처리량에 직결된다.
- `dev-dashboard` — `opencode/flint-40b-free#high`: Streamlit 데이터프레임·레이아웃 중심의 UI 작업은 40B급 코드 생성으로 충분하다. DB는 읽기 전용이라 실패해도 데이터를 훼손하지 않아 중간 등급 모델의 위험이 낮다.
- `dev-publisher` — `opencode/mimo-v2.6-flash-free`: Phase 2의 정적 JSON 발행·웹 페이지는 입력이 이미 확정된 저위험 작업이고, 반복 실행 빈도가 높아 가장 가벼운 모델을 배정했다.

**한계**: 모델 카탈로그는 이 모델들의 벤치마크·컨텍스트 크기를 공개하지 않는다. 위 배치는 계열·제공사·variant 지원 여부에 근거한 **추정**이며, 실제 품질이 기대와 다르면 위 표와 설정 파일을 함께 조정한다. NVIDIA 무료 엔드포인트는 trial 약관이 적용되므로 개인정보·기밀 데이터를 넣지 않는다(불변식 7).

- `SPEC.md`, `PRD.md`, `AGENTS.md`와 계약은 **오케스트레이터만** 수정한다. 다른 에이전트는 변경을 제안한다.
- 소유자가 없는 새 경로가 필요하면 오케스트레이터가 먼저 소유자를 정하고 이 표와 에이전트 권한을 갱신한다.
- 사람(사용자)은 모든 경로를 수정할 수 있으며, 사람의 결정이 이 문서보다 우선한다.

---

# 3. 모듈 경계와 데이터 흐름

```
 [외부 API] ──▶ collector ──▶ traffic_observation, collection_log
                                   │
                                   ▼
                           preprocessing ──▶ segment_traffic_5min
                                                  │
                                                  ▼
                                    prediction ──▶ traffic_prediction, model_registry, model_evaluation
                                                  │
                         ┌────────────────────────┴───────────────┐
                         ▼                                        ▼
                    dashboard (읽기 전용)                publisher ──▶ publish_log, latest.json
```

| 테이블 | 쓰기 소유 모듈 | 읽기 허용 |
|---|---|---|
| `road_segment`, `segment_link`, `calendar_info` | database (`scripts/`) | 전체 |
| `traffic_observation`, `collection_log` | collector | preprocessing, dashboard |
| `segment_traffic_5min` | preprocessing | prediction, dashboard, publisher |
| `traffic_prediction`, `model_registry`, `model_evaluation` | prediction | dashboard, publisher |
| `publish_log` | publisher | dashboard |

- 테이블에 쓰는 모듈은 하나뿐이다. 다른 모듈은 읽기만 한다.
- DB 연결과 공통 쿼리 헬퍼는 `database/`가 제공하고, 다른 모듈은 이것만 사용한다.
- 시각 변환(KST), 로깅 설정, 경로 설정은 `common/`과 `config/`의 공용 코드를 사용한다. 모듈마다 따로 만들지 않는다.

---

# 4. 계약 (Contracts)

## 4.1 계약 목록

| ID | 계약 | 근거 | 산출물 |
|---|---|---|---|
| C-01 | DB 스키마 | SPEC 5장 | `docs/contracts/C-01-db-schema.md`, `tests/contracts/test_c01_schema.py` |
| C-02 | 수집 원본 레코드 형식 | SPEC 4.3 | `docs/contracts/C-02-observation.md` |
| C-03 | 전처리 출력과 특성 | SPEC 6장 | `docs/contracts/C-03-features.md` |
| C-04 | 예측 결과와 모델 등록 | SPEC 5.5~5.6, 7장 | `docs/contracts/C-04-prediction.md` |
| C-05 | 공개 JSON | SPEC 20.3 | `docs/contracts/C-05-public-json.md`, JSON Schema |
| C-06 | 모듈 공개 진입점 | SPEC 7.6 | `docs/contracts/C-06-entrypoints.md` |

## 4.2 계약 상태

| 상태 | 의미 | 구현 가능 여부 |
|---|---|---|
| `draft` | 작성 중 | 시험 구현만 가능 |
| `frozen` | 확정. 이 버전 기준으로 병렬 개발 | 가능 |
| `revising` | 변경 요청 처리 중 | 기존 frozen 버전 기준으로 계속 개발 |

계약 문서 맨 위에 `상태`, `버전(v1, v2 …)`, `영향 받는 에이전트`를 적는다.

## 4.3 계약 변경 절차

1. 변경이 필요한 에이전트는 **직접 수정하지 않고** 보고서에 변경 요청(CR)을 적는다: 무엇을, 왜, 영향 범위.
2. 오케스트레이터가 승인 여부를 정하고, 승인하면 계약 버전을 올리고 계약 테스트를 갱신한다.
3. 오케스트레이터가 영향 받는 에이전트에게 후속 작업을 배정한다.
4. 계약을 깨는 변경은 영향 받는 모든 모듈의 테스트가 통과할 때까지 통합하지 않는다.

---

# 5. 작업 흐름

## 5.1 단계 (Wave)

| Wave | 내용 | 병렬 실행 |
|---|---|---|
| **W0. 기반** | 저장소 초기화, 공용 코드, 리서치 착수, 계약 초안 | `researcher` 여러 주제 병렬 + 오케스트레이터 계약 작성 |
| **W1. 계약 확정** | 리서치 결과를 반영해 C-01~C-06을 frozen으로 확정, 공용 픽스처 생성 | 개발 에이전트별 계약 검토 병렬 |
| **W2. 모듈 개발** | 각 모듈을 픽스처 기준으로 구현 | `dev-collector`, `dev-data`, `dev-ml`, `dev-dashboard` 병렬 (`dev-publisher`는 Phase 2) |
| **W3. 통합** | 실제 데이터로 파이프라인 연결, 통합 테스트 | 오케스트레이터 주도, 실패 모듈만 수정 배정 |
| **W4. 반복 개선** | 데이터 축적에 따른 모델·전처리 개선 | 개선 주제별 병렬 |

**슬라이스 반복**: W0~W3은 한 번으로 끝나지 않는다. 각 슬라이스(Slice 0, 1, 2 …)마다 그 슬라이스에 필요한 범위만 계약을 확정·확장하고, W2(병렬 개발)와 W3(통합)을 반복한다. 계약을 넓힐 때는 4.3 절차대로 버전을 올린다. 슬라이스 정의는 `docs/superpowers/specs/2026-11-18-thin-slice-design.md`, 슬라이스별 구현 계획은 `docs/superpowers/plans/`를 따른다.

리서치는 W0에서 끝나지 않는다. 개발 중 새 질문이 생기면 언제든 `researcher` 작업으로 분리해 병렬로 진행한다.

## 5.2 오케스트레이터의 실행 루프

1. `docs/tasks/BOARD.md`에서 선행 작업이 끝난 `ready` 작업을 고른다.
2. **서로 다른 소유 경로의 작업은 동시에** 서브에이전트로 실행한다. 같은 소유자의 작업은 순서대로 실행한다.
3. 각 서브에이전트에 작업 지시서(5.4)를 전달한다. 서브에이전트는 새 컨텍스트에서 시작하므로 필요한 정보를 모두 담는다.
4. 결과 보고(7장)를 받으면 `reviewer`로 검토하고, 통과하면 커밋하고 BOARD를 갱신한다.
5. 보고서의 CR, 추가 리서치 질문, 차단 사항을 새 작업으로 등록한다.

## 5.3 다른 모듈의 변경이 필요할 때

- 다른 모듈의 코드를 직접 고치지 않는다.
- 필요한 변경을 보고서의 "요청 사항"에 적고, 그동안은 계약에 맞는 임시 대역(stub, fake)을 **자기 테스트 코드 안에서만** 사용한다.

## 5.4 작업 지시서 형식

오케스트레이터가 서브에이전트를 실행할 때 다음을 포함한다.

```
작업 ID: D-DAT-02
제목: 5분 구간 집계 구현
소유 에이전트: dev-data
관련 계약: C-01 v1 (frozen), C-03 v1 (frozen)
SPEC 근거: 6.1, 6.2, 6.3
입력: tests/fixtures/obs_sample.sqlite
완료 기준:
  - preprocessing.run(until=...) 진입점 구현 (C-06)
  - 거리 가중 조화평균, 70% 부분 관측 규칙 테스트 통과
  - forward fill 2 bin 이하 규칙 테스트 통과
  - preprocessing/README.md에 집계 규칙·진입점 반영
범위 밖: 특성 생성(D-DAT-03), 이상치 기준 수치 변경
```

## 5.5 버전 관리

- 저장소는 git으로 관리한다. **커밋은 오케스트레이터만** 한다. 여러 에이전트가 같은 저장소에서 동시에 커밋하면 충돌이 생기기 때문이다.
- 개발 에이전트는 `git status`, `git diff`로 상태를 확인할 수 있지만 커밋·브랜치·push는 하지 않는다.
- 커밋 메시지에 작업 ID를 넣는다: `[D-DAT-02] 5분 구간 집계 구현`
- 큰 실험(모델 구조 변경 등)은 오케스트레이터가 별도 worktree를 만들어 격리할 수 있다.

---

# 6. 프로젝트 불변식 (모든 에이전트 공통)

다음은 SPEC의 핵심 규칙이며 어떤 작업에서도 어기지 않는다. `reviewer`는 이 목록을 기준으로 검토한다.

1. **가짜 데이터를 실제처럼 쓰지 않는다.** 합성 데이터는 `tests/fixtures/`에서 테스트용으로만 사용하고, DB 운영 파일·대시보드·공개 페이지에 들어가지 않게 한다. 픽스처 파일에는 `synthetic` 표시를 남긴다.
2. **결측을 0으로 바꾸지 않는다.** 수집 실패, 누락은 NULL 또는 플래그로 남긴다. (SPEC 4.5, 6.3)
3. **미래 정보를 쓰지 않는다.** 특성은 `available_at ≤ base_time` 데이터만 사용하고, 결측 보간은 과거 값만 사용한다. (SPEC 6.6)
4. **모든 시각은 KST(+09:00) ISO8601**로 다루고 `common/`의 시간 헬퍼를 사용한다.
5. **확인되지 않은 외부 사실을 추측해서 넣지 않는다.** API 필드명, 링크 ID, 코드값 등은 `docs/research/`의 근거가 있어야 한다. 근거가 없으면 `TODO(R-xx)` 표시와 함께 설정값으로 분리한다.
6. **비밀정보를 다루지 않는다.** `.env` 파일을 읽거나 출력하지 않는다. 인증키는 코드·로그·문서·테스트에 쓰지 않는다. 필요한 키 이름은 `.env.example`에만 적는다.
7. **외부 서비스로 개인정보를 보내지 않는다.** 웹 검색, 외부 API 요청에 사용자 이름·이메일·로컬 경로 등을 포함하지 않는다.
8. **공식 API만 사용한다.** 웹 화면 스크레이핑은 이용약관 확인과 사람의 승인 전에는 구현하지 않는다.
9. **테이블 쓰기 소유권(3장)을 지킨다.**

---

# 7. 보고 형식

모든 서브에이전트는 작업 종료 시 다음 형식으로 보고한다. 오케스트레이터는 이 보고로 BOARD를 갱신한다.

```markdown
## 보고: <작업 ID> <제목>
- 상태: done | partial | blocked
- 변경 파일: (경로 목록)
- 테스트: (실행한 명령과 결과 요약. 실패는 출력 포함)
- 완료 기준 충족: (기준별 ✅/❌)
- 가정·추측한 부분: (없으면 "없음")
- 변경 요청(CR): (계약·다른 모듈·SPEC 변경 필요 사항, 없으면 "없음")
- 리서치 요청: (새로 확인이 필요한 외부 사실)
- 의존성 추가 요청: (requirements 추가가 필요한 패키지와 이유)
- 문서 갱신: (갱신한 README·문서 경로와 바뀐 내용. 갱신하지 않았다면 그 이유)
- 다음 작업 제안:
```

---

# 8. 리서치 프로토콜 (`researcher`)

- 결과는 `docs/research/R-xx-<주제>.md`로 작성한다. 형식은 `docs/research/README.md`의 템플릿을 따른다.
- 모든 사실에 **출처 URL과 확인 일자**를 붙인다. 공식 문서 > 공공기관 자료 > 기타 순으로 신뢰한다.
- 사실, 추론, 미확인을 구분해서 쓴다. 확신도(높음/중간/낮음)를 적는다.
- SPEC에 영향을 주는 발견은 "SPEC 변경 제안" 절에 적는다. SPEC을 직접 고치지 않는다.
- API 실제 호출이 필요하면 사람에게 요청한다(인증키는 사람이 관리). 받은 샘플 응답은 비밀정보를 지운 뒤 `docs/research/samples/`에 저장한다.
- 여러 주제는 서로 독립된 리서치 작업으로 나눠 병렬로 진행한다.

---

# 9. 개발 프로토콜 (`dev-*`)

1. **시작 전**: 작업 지시서, 관련 계약(frozen 버전), SPEC 근거 절, 관련 리서치 문서를 읽는다.
2. **구현**: 자기 소유 경로만 수정한다. 다른 모듈은 C-06 진입점과 C-01 테이블로만 접근한다.
3. **테스트**: 새 기능마다 pytest 테스트를 작성한다. 계약 테스트(`tests/contracts/`)와 자기 모듈 테스트가 모두 통과해야 한다.
4. **문서화(필수)**: 동작·공개 함수·CLI·설정값·화면·운영 절차가 바뀌면 같은 작업 안에서 자기 소유 문서(모듈 `README.md` 등)를 갱신한다. 문서는 "지금 코드가 실제로 하는 일"과 일치해야 한다. 계약·SPEC·BOARD·루트 README처럼 오케스트레이터 소유 문서의 변경이 필요하면 보고서에 적는다.
5. **보고**: 7장 형식으로 보고하고, "문서 갱신" 항목을 반드시 채운다.

## 코드 규약

- Python 3.11, 타입 힌트 필수, 공개 함수에 docstring
- 설정값(임계값, 경로, URL)은 `config/`에서 읽는다. 코드에 하드코딩하지 않는다.
- 로깅은 `common/`의 로거 설정을 사용한다. `print`로 운영 로그를 남기지 않는다.
- 외부 네트워크 호출은 `collector`(수집 API)와 `publisher`(업로드)에서만 한다. 테스트에서는 네트워크를 호출하지 않고 저장된 샘플 응답을 사용한다.
- 의존성 추가는 직접 하지 않고 보고서로 요청한다.

---

# 10. 완료 정의 (Definition of Done)

작업은 다음을 모두 만족해야 `done`이다.

- [ ] 작업 지시서의 완료 기준을 모두 충족
- [ ] 자기 모듈 테스트와 계약 테스트 통과 (실행 결과 첨부)
- [ ] 소유 경로 밖의 변경 없음
- [ ] 6장 불변식 위반 없음 (`reviewer` 확인)
- [ ] 추측한 외부 사실 없음, 또는 `TODO(R-xx)`로 분리
- [ ] 바뀐 동작이 모듈 README 등 문서에 반영됨 (9장 4항, 오케스트레이터가 커밋 전 diff로 확인)
- [ ] 7장 형식의 보고 제출

---

# 11. 차단·충돌 처리

| 상황 | 처리 |
|---|---|
| 계약이 모호하거나 모순 | 작업을 `blocked`로 보고하고 CR 제출. 추측해서 구현하지 않음 |
| 외부 사실이 필요 | 리서치 요청을 보고하고, 그 부분은 설정값·TODO로 분리한 채 나머지 진행 |
| 다른 모듈의 버그 발견 | 직접 고치지 않고 보고. 오케스트레이터가 소유자에게 배정 |
| 같은 경로를 두 작업이 수정해야 함 | 오케스트레이터가 순차 실행으로 바꾸거나 작업을 다시 나눔 |
| 사람의 결정이 필요 (비용, 법적 판단, 외부 공개, 비밀정보) | 오케스트레이터가 사람에게 질문하고, 답을 받을 때까지 해당 작업 보류 |
