# 작업 현황판

**오케스트레이터만 수정한다.** 다른 에이전트는 보고서(`AGENTS.md` 7장)로 상태를 알린다.

상태: `ready`(시작 가능) · `waiting`(선행 작업 대기) · `in_progress` · `review` · `done` · `blocked`

진행 방식은 슬라이스 반복이다(`docs/superpowers/specs/2026-11-18-thin-slice-design.md`). 같은 **병렬 그룹**의 작업은 소유 경로가 겹치지 않아 동시에 실행할 수 있다.

---

## 리서치

| ID | 주제 | 상태 | 남은 일 |
|---|---|---|---|
| R-01 | 경찰청 교통소통정보 API | done (실호출 확인 필요) | 사람이 키로 응답 형식을 확인한다. 지도 URL만 제공되면 수집원에서 제외한다 |
| R-02 | ITS 소통정보 API | done (실호출 확인 필요) | 창원대로 포함 여부, 갱신 간격, 결측 표현 확인 (Slice 0 Task 10) |
| R-03 | 표준노드링크 | partial | 파일을 받아 두었다(`data/reference/NODELINKDATA_2026-11-11/`). 창원대로 링크 표를 작성하는 R-03b가 남았다 |
| R-04 | UTIS | done | 자동 수집원으로 쓰지 않고 수동 대조용으로만 쓴다 |
| R-05 | 공휴일·학사일정 | done | Slice 1의 달력 적재에서 사용한다 |
| R-03b | 표준노드링크에서 창원대로 출근 방향 링크 표 추출 → `config/segment_links.csv` 후보 | ready | - |

## Slice 0 — 얇은 전체 흐름 (`docs/superpowers/plans/2026-11-18-slice0.md`)

| Task | ID | 작업 | 소유 | 선행 | 병렬 그룹 | 상태 |
|---|---|---|---|---|---|---|
| 1 | T-00 | 저장소 초기화, 문서 갱신 | orchestrator | - | - | done |
| 2 | T-01 | 공용 시간·로깅·레코드·설정 | orchestrator | 1 | - | done |
| 3 | C-01/02/06, F-01 | 계약 v1, 공용 합성 픽스처 | orchestrator | 2 | - | done |
| 4 | D-DAT-01 | DB 연결·스키마·시드 | dev-data | 3 | A | done |
| 5 | D-COL-01 | ITS 어댑터, `run_once` | dev-collector | 3 | A | done |
| 7 | D-ML-00 | 현재 속도 유지 예측 | dev-ml | 3 | A | done |
| 8 | D-DSH-00 | 대시보드 v0 | dev-dashboard | 3 | A | done |
| 6 | D-DAT-02a | 5분 구간 집계 v0 | dev-data | 4 | B | done |
| 9 | D-COL-02 | 스케줄러 | dev-collector | 5 | B | done |
| 10 | I-01 | 통합 시험, 실제 호출, 상시 수집 시작 | orchestrator + 사람 | 6, 7, 8, 9 | - | in_progress — 실제 호출·전체 흐름 확인 완료(2026-11-19), 남은 일: [사람] 작업 스케줄러 등록·절전 해제·대시보드 화면 확인, 3일 연속 성공률 95% |

## 즉시 작업 (사용자 요청)

| ID | 작업 | 소유 | 선행 | 상태 |
|---|---|---|---|---|
| T-OPS-01 | 에이전트별 모델 지정과 제한 시 대체 모델 규칙 문서화 | orchestrator | - | done |
| D-DSH-01 | 구간별 현재 속도 표의 '상태'(원활/서행/정체) 글씨 색 구분 | dev-dashboard | - | in_progress |

### Slice 1 후보 (리뷰에서 나온 후속 과제)

| 출처 | 내용 |
|---|---|
| Task 7 리뷰 | skipped 예측 행이 같은 base_time의 늦은 정상 예측을 막음(INSERT OR IGNORE) → skipped만 덮어쓰기 |
| Task 7 리뷰 | backfill 조회 범위 제한, 예외 시 rollback |
| Task 8 리뷰 | degraded 예측 회색 표시, 구간별 지연 판단, 수집 시각 별도 표시 |
| Task 6 | 70% 부분 관측 기준, forward fill(2 bin), 측도 `speed_side` |
| 실측 | `partial` 원인: 부모 링크가 체인에 없는 4140068801(S3 본선)·4150149001(S6 측도) — ITS 응답에서 대응 링크 확인 |
| 방향 검증 | 4140071400(S3)의 ITS 끝 교차로(41400574)가 2026 노드링크(41402077)와 다름 — 링크 경계 변경으로 추정, ITS 쪽 후속 링크 확인해 매핑 보정 |
| 방향 검증 | 평일 07:30~08:30 데이터로 우리 방향(팔용→성산)과 반대 방향(ID −100) 속도 비교해 출근 방향 정체를 실측 확인 |
| 실측 | ITS 응답 6,792건 중 창원대로 37건만 필요 — 조회 범위(bbox)를 창원대로 좌표로 좁혀 저장량 축소 |

## 다음 슬라이스 (계획 작성 전)

| 슬라이스 | 주요 작업 |
|---|---|
| Slice 1 | 경찰청 어댑터(필요 시), 갱신 정지·70% 부분 관측·forward fill, 기준 모델 3종, 평가 지표, 시계열 그래프, `calendar_info` 적재 |
| Slice 2 | as-of 특성(C-03), XGBoost(C-04), 성능 화면 |
| Slice 3 | walk-forward 정식 평가, 구간별 모델 비교 |
| Slice 4 (선택) | 시민 공개 (R-07, R-08, C-05, D-PUB-*) |

---

## 결정·변경 요청(CR)·차단 기록

| 일자 | 출처 | 내용 | 처리 |
|---|---|---|---|
| 2026-11-18 | R-01, R-02 | 경찰청 API는 링크 데이터가 아닐 가능성이 높아, 첫 수집원을 ITS로 바꾼다 | Slice 0 계획에 반영 |
| 2026-11-18 | R-05 | `calendar_info`의 방학·휴가 컬럼에서 DEFAULT 0을 빼고 NULL 허용 | C-01 v1에 반영 예정 (Task 3) |
| 2026-11-18 | 실행 | 소유 경로가 다른 dev 작업은 병렬로 실행하고, 커밋은 오케스트레이터만 한다(AGENTS.md 우선) | Ruling |
| 2026-11-18 | R-03b | 8구간 후보를 6구간(S1~S6)+참고 S0로 재편 | SPEC v1.3 |
| 2026-11-18 | Task 5 리뷰 | `segment_link.source`는 링크 ID 체계 출처, 수집원별로 거르지 않음 | C-01 v1.1, Ruling |
| 2026-11-19 | 첫 ITS 실측 | ITS가 창원대로를 제공함(창원 bbox 6,792 링크 중 창원대로 37개). ITS는 분할 전 링크(끝 00) 단위로 값을 주며 `속도×통행시간` 역산 길이가 분할 링크 길이 합과 일치 → 분할 링크를 부모에 합쳐 링크 39개로 재구성(`config/build_segment_links.py`). 첫 실측 DB는 `data/traffic_firstfetch_20261119.db`로 보관 | Ruling |
| 2026-11-19 | 최종 리뷰 I3 | **수집 성공률 정의**: 평일 06:00~10:00의 5분 bin(48개) × 예측 대상 구간 6개 중 `segment_traffic_5min.speed IS NOT NULL`(imputed 제외)인 비율. 회차 상태(`partial`·`no_update`)가 아니라 실제로 쓸 수 있는 데이터 기준이다. 대상 링크 2개가 ITS에 없어 상태가 늘 `partial`이고, ITS 갱신 전 회차는 `no_update`가 정상이기 때문. Slice 0 완료 = 평일 3일 연속 95% 이상 | Ruling |
| 2026-11-19 | 최종 리뷰 I2 | pytest 로그를 임시 폴더로 격리(`tests/conftest.py`). 이전 테스트가 남긴 합성 로그 줄은 `logs/app.log` 978행까지 — 그 이전 로그로 성공률을 세지 않는다 | 수정 |
| 2026-11-19 | 방향 검증 | 노드 연결(본선 77개 끊김 0), 좌표 진행(86개 모두 소계광장→성주광장 축 방위 124° 방향, 역행 0), ITS 시작·끝 교차로 대조(36/37 일치, 역방향 0), 반대 방향 짝 링크 37/37 존재 → 방향 정상. ITS는 교차로 중심 노드(끝 00), 2026 노드링크는 방향별 노드(끝 02·03)라 노드 앞 8자리로 비교. 스크립트 `docs/research/scripts/verify_direction.py`, 결과 `docs/research/samples/direction_check_2026-11-19.txt` | 확인 |
