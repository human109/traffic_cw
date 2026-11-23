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
| R-03 | 표준노드링크 | done | 파일: `data/reference/NODELINKDATA_2026-11-11/`. 링크 표는 R-03b |
| R-04 | UTIS | done | 자동 수집원으로 쓰지 않고 수동 대조용으로만 쓴다 |
| R-05 | 공휴일·학사일정 | done | Slice 1의 달력 적재에서 사용한다 |
| R-03b | 표준노드링크에서 창원대로 출근 방향 링크 표 추출 → `config/segment_links.csv` 후보 | done | `config/build_segment_links.py`로 반영 |
| R-06b | 링크 보정, 출근 방향 실측 비교 | done (001a895) | 평일이 쌓이면 재실행. S6 반대 방향 두 링크 상시 저속 원인은 사람 확인 |
| R-xx | 2027 산단 휴가 기간, 임시공휴일 지정 여부 | 미착수 | 2027 달력 반영 전 |

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
| T-OPS-02 | GitHub 공개 준비 점검: `.gitignore` 보강(`.obsidian/`), MIT LICENSE 추가 | orchestrator | - | done |
| D-COL-05 | 저장 범위 밖 관측 행 정리(`collector/maintenance.py` purge, dry-run 기본) | dev-collector | - | done (reviewer 승인, tests/collector+contracts 59 passed) |
| D-DAT-02b | 전처리 규칙 완성: `preprocessing/rules.py` 테스트·`aggregate` 배선 | dev-data | D-DAT-02a | done (Slice 1 Task 6에서 완료) |
| D-DOC-01 | 문서 누락 보완: `dashboard/README.md`에 D-DSH-02·03 반영, 루트 README에 운영 명령 | dev-dashboard, orchestrator | - | done |
| T-OPS-05 | 서브에이전트 문서화 의무화: AGENTS.md 7·9·10장, dev-*/orchestrator/reviewer 프롬프트 | orchestrator | - | done |
| D-DSH-U01 | 구간별 현재 속도 표의 '상태'(원활/서행/정체) 글씨 색 구분 | dev-dashboard | - | done (reviewer 승인, 24 passed) |

### 남은 후속 과제 (리뷰 Minor, 2026-11-20 정리)

| 출처 | 내용 | 소유 |
|---|---|---|
| D-COL-06 리뷰 | `prune_raw`: `raw_dir` 빈 문자열·공백 거부, 저장소 루트 기준 해석(connect와 통일) / 폴더별 try로 rmtree 실패 시 계속 / `--once --maintenance` 생략 동작 문서 / scheduler.py 끝 빈 줄 | dev-collector |
| D-COL-05 리뷰 | purge `main()` CLI 테스트(dry-run 무삭제, `--apply` 삭제+VACUUM), 안전 문구("백업은 자동이 아니다", 해석된 DB 경로 출력), `finally` DROP TABLE 예외 안전·행 수 불일치 분기 테스트 | dev-collector |
| D-COL-07 리뷰 | 저장소 루트 계산이 `database/db.py`와 `collector/paths.py`에 중복 — `common/`으로 공용화 검토(CR 후보) | orchestrator(common) |
| D-ML-03 리뷰 | 모듈 docstring의 ValueError 조건 서술을 실제 조건(target HH:MM 충돌)으로, 중복 horizon 메시지 | dev-ml |
| D-DAT-05 리뷰 | 위 m2~m4는 반영 완료. 남은 것 없음 | - |

정리하며 닫은 항목(코드에서 확인): Task 7 skipped 덮어쓰기·backfill 범위·rollback, Task 8 회색 표시·구간별 지연, Task 6 70%·forward fill·speed_side, S3 링크 보정(R-06b), 방향 실측 비교(R-06b 2부), 평가 시각 settings화·`--once --evaluate` 문서(D-COL-06), `width='stretch'`(D-DSH-02), dow_mean 하한·인덱스·경고(D-ML-02, D-DAT-05), ITS bbox 축소(`its_bbox`).

## Slice 1.5 — 운영 보강 (2026-11-20 시작, 계약 C-01 v1.3 · C-06 v2.2)

| ID | 작업 | 소유 | 상태 |
|---|---|---|---|
| D-DAT-05 | `schema.sql`에 `ix_pred_target_time` 반영, `scripts/collection_rate.py`(성공률), `scripts/backup_db.py`(일일 백업 14일 보관) | dev-data | done (7c50593) |
| D-COL-06 | `maintenance.prune_raw`(원본 30일 보관), 스케줄러에 일일 백업(03:00)·원본 정리 job, 평가 시각을 settings로, `--once --evaluate` 문서 | dev-collector | done (b6b204b) |
| D-ML-02 | dow_mean 조회를 세그먼트당 1회·기간 하한으로, calendar 누락 경고 날짜별 1회, recent15 imputed→degraded 테스트 | dev-ml | done (cc4ef50) |
| D-DSH-02 | 성능 탭에 날짜별 수집 성공률(목표 95%), `use_container_width` → `width` | dev-dashboard | done — 읽기 전용 표시 변경이라 reviewer 대신 오케스트레이터가 diff·테스트·실DB AppTest로 확인(Ruling) |
| D-DSH-03 | 시계열 그래프 미표시 버그(기본 모델 persistence, 실제·예측 중 하나만 있어도 표시) | dev-dashboard | done (9edd0e8) |
| D-COL-07 | `prune_raw` 안전 보강(빈 경로 거부·루트 기준·폴더별 try), purge CLI 테스트·안내 문구·DROP 예외 안전, `raw_file` 상대 경로 유지 | dev-collector | done (9182f38) |
| D-ML-03 | dow_mean 하한을 settings로(C-04 v1.3), HH:MM 병합 가정 가드, 경계 테스트 | dev-ml | done (d6b95e5) |
| D-DSH-04 | UI 개선: 현재 표 행 클릭 → 그 구간 시계열(사람 요구), 화면 전환을 상태·URL(`view`,`seg`)로, 상태 배지 대비 4.5:1, 등급 띠 그래프·등급 색 히트맵, 기간 선택, 성공률 표시 로직 data.py로 | dev-dashboard | done — 1차 보고는 app.py 미변경인데 done으로 보고되어 반려, 재작업 후 운영 DB AppTest(세 화면·URL·행 클릭 시뮬레이션)로 결함 6건 발견·수정 확인(오케스트레이터) |
| R-06b-2 | 출근 방향 최종 비교(07:00~09:00 전체) | researcher | done (001a895) |
| I-03 | 운영 반영: 인덱스 적용·첫 백업(11/20 08:56), 수집기 재시작(11/20 11:06, job 3개 등록 로그 확인). 남은 일: 11/21 03:00 백업 생성 확인, Slice 0 완료 판정(11/20 99.3% ✅, 11/23·11/24) | orchestrator + 사람 | in_progress |

## 원이대로 확장 (설계 `docs/superpowers/specs/2026-11-23-wonidaero-corridor-design.md`, 계획 `docs/superpowers/plans/2026-11-23-wonidaero-corridor.md`)

계약: C-01 v1.4 · C-02 v2.2 · C-04 v1.4 · C-06 v2.3, SPEC v1.4

| ID | 작업 | 소유 | 상태 |
|---|---|---|---|
| R-09 | 원이대로 링크 표·구간 후보 | researcher | done (60fce90) |
| W-01 | 계약·SPEC·설정(`corridors`, `target_corridors`)·구간 시드 W0~W5·링크 35행·픽스처(`fixture_db_two`) | orchestrator | done |
| W-02 | `init_db` 마이그레이션(`model_evaluation.road_name`), schema.sql 동기화, 도로별 성공률 `rate(..., road_name)` | dev-data | done (ccf81cb). 운영 DB 적용 11/23 12:20(백업 `traffic_before_wonidaero_20261123.db` = backup_db 스냅숏): 평가 504행 '창원대로', 구간 13(원이대로 6은 is_target=0), 링크 74 |
| W-03 | 원본 재적재 `maintenance.reload_raw` | dev-collector | done (a62eefc). 운영 dry-run 11/19~23: 파일 1,136, 넣을 행 92,778, 약 7분 |
| W-04 | 도로별 평가 집계, 구간 순서 (도로, seq) | dev-ml | done (7f34ad9) |
| W-05 | 대시보드 도로 선택 `?road=` | dev-dashboard | done — 합성 두 도로 DB·운영 DB AppTest 8개 시나리오 예외 없음(오케스트레이터) |
| W-06 | 운영 반영(11/24 판정 후): 백업 → init_db → 재적재 → 재집계 → `target_corridors`에 원이대로 → 재시작 | orchestrator + 사람 | waiting |

## 이후 일정

| 시점 | 단계 |
|---|---|
| 11/24(화) | Slice 0 완료 판정 (평일 3일 성공률 ≥ 95%) |
| 11/23~12/2 | Slice 2 준비: C-03 특성 계약, 특성 생성·XGBoost 학습 코드(합성) |
| 12/3~ | Slice 2: 실데이터 첫 학습, 기준 모델 비교 |
| 12/10 무렵 | dow_mean 기준 모델 표본 3주 도달 |
| 12월 말 | 겨울방학 시작 (계절 구분 표시) |
| 2027-01-14 무렵 | Slice 3 정식 walk-forward 평가 |
| 선택 | Slice 4 시민 공개 |

## 다음 슬라이스 (계획 작성 전)

| 슬라이스 | 주요 작업 |
|---|---|
| Slice 1 | done (11/20). 경찰청 어댑터는 보류(R-01) |
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
| 2026-11-23 | 로그 회전 사고 (T-OPS-06) | 11/23 00:00부터 `logs/app.log` 기록 중단("Logging error"). 원인: D-DSH-02 이후 대시보드가 `scripts.collection_rate`를 통해 같은 `app.log`를 열어, 수집기의 자정 회전(rename)이 Windows 파일 잠금으로 실패하고 이후 모든 기록이 실패. `app.log.2026-11-21`도 없음(같은 원인으로 유실 추정). 수집·백업·평가는 정상(DB·백업 파일로 확인). 수정: 회전 실패 시 이어 쓰고 1시간 뒤 재시도하는 `SafeTimedRotatingFileHandler`, 프로세스별 로그 파일(`LOG_FILE`, 대시보드 `dashboard.log`) | 수정, 재시작 필요 |
| 2026-11-20 | 첫 운영 지표 | 수집 성공률 11/20 99.3%(286/288). 10:05 첫 자동 평가 112행. 07~09시 전체 구간 MAE: persistence h5 2.53 / h15 3.16 / h30 5.54, recent15 h5 2.36 / h15 2.32 / h30 3.34 — recent15는 08:06 재시작 이후만 있어 표본·시간대가 달라 직접 비교 불가, 하루치 | 기록 |
| 2026-11-20 | Slice 1 Task 8 운영 반영 | 백업 `data/backup/traffic_before_slice1_20261120.db` → `init_db`(링크 39: 4140068801 닫고 4140068800 추가, 달력 730행) → 4140068801은 처음부터 잘못 매핑이라 `valid_to=valid_from`(무효)로 정정 → `segment_traffic_5min` 비우고 11/19 09:55~ 전체를 Slice 1 규칙으로 재집계(1,855행: ok 1,746 / partial 51 / imputed 35 / missing 23). 기록 `docs/ops/2026-11-20-reaggregate-slice1.py`. S3 본선 5/5 관측 확인. 대시보드 AppTest 오류 0 | 완료, 수집기 재시작 대기 |
| 2026-11-19 | 모델 운영 | 기본 무료 모델 사용 한도 초과 → 대체 모델 `nvidia/deepseek-ai/deepseek-v4.1-flash`가 2026-11-16 폐기(모델 목록에는 active로 표시됨). 사람 승인으로 reviewer·researcher·dev-data·dev-ml 대체 모델을 `nvidia/z-ai/glm-5.3-flash#thinking`으로 교체. dev-dashboard는 `nvidia/meta/muse-glimmer-30b#high`로 진행 | 사람 결정 |
| 2026-11-23 | 모델 운영 | `opencode/longcat-2.5-free` 카탈로그 삭제로 researcher 세션 실패(로그 11/22 23:58 `Model unavailable: opencode/longcat-2.5-free`). researcher 기본 모델을 `opencode/beam-free#high`로 교체(1M 컨텍스트·tool strict·학습 미사용)하고 AGENTS.md 2장 표·선정 이유와 orchestrator 대체 모델 표를 갱신. 전수 점검 결과 나머지 기본 모델 8종과 대체 모델 3종은 전량 active이며 variant도 유효 | 수정 |
| 2026-11-19 | 운영 DB 정리 | 저장 범위 밖 46,725행 삭제·VACUUM(12.7MB→1.9MB), 6,435행·117링크 유지. 백업 `data/backup/traffic_before_purge_20261119.db` | 사람 승인 |
| 2026-11-19 | 최종 리뷰 I3 | **수집 성공률 정의**: 평일 06:00~10:00의 5분 bin(48개) × 예측 대상 구간 6개 중 `segment_traffic_5min.speed IS NOT NULL`(imputed 제외)인 비율. 회차 상태(`partial`·`no_update`)가 아니라 실제로 쓸 수 있는 데이터 기준이다. 대상 링크 2개가 ITS에 없어 상태가 늘 `partial`이고, ITS 갱신 전 회차는 `no_update`가 정상이기 때문. Slice 0 완료 = 평일 3일 연속 95% 이상 | Ruling |
| 2026-11-19 | 최종 리뷰 I2 | pytest 로그를 임시 폴더로 격리(`tests/conftest.py`). 이전 테스트가 남긴 합성 로그 줄은 `logs/app.log` 978행까지 — 그 이전 로그로 성공률을 세지 않는다 | 수정 |
| 2026-11-19 | 방향 검증 | 노드 연결(본선 77개 끊김 0), 좌표 진행(86개 모두 소계광장→성주광장 축 방위 124° 방향, 역행 0), ITS 시작·끝 교차로 대조(36/37 일치, 역방향 0), 반대 방향 짝 링크 37/37 존재 → 방향 정상. ITS는 교차로 중심 노드(끝 00), 2026 노드링크는 방향별 노드(끝 02·03)라 노드 앞 8자리로 비교. 스크립트 `docs/research/scripts/verify_direction.py`, 결과 `docs/research/samples/direction_check_2026-11-19.txt` | 확인 |
