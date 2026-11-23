# 창원대로 아침 출근길 교통 흐름 예측 시스템
## Software Requirements & Technical Specification

| 항목 | 내용 |
|---|---|
| 문서 버전 | v1.4 |
| 작성일 | 2026-11-04 (v1.0) / 2026-11-18 (v1.1, v1.2) |
| 관련 문서 | `PRD.md` v1.1, `AGENTS.md` (개발 방식) |
| 프로젝트명 | Changwon Road Traffic Prediction |
| 개발 유형 | Python 기반 교통 데이터 수집 및 예측 시스템 |
| 개발 환경 | 로컬 PC (Windows) |
| 대상 지역 | 경상남도 창원시 창원대로, 원이대로 |
| 주요 사용자 | 시스템 개발자 및 교통 흐름 분석 담당자 |

## 변경 이력

| 버전 | 일자 | 주요 변경 내용 |
|---|---|---|
| v1.0 | 2026-11-04 | 최초 작성 |
| v1.1 | 2026-11-18 | 분석 구간 재정의(5→7개, 지하차도 처리), 수집 시간·기간 확대, DB 스키마 보완(segment_link, segment_traffic_5min, model_registry, model_evaluation), 미래 정보 누출 방지 규칙, 이상치·결측 기준 수치화, 예측 실행 파이프라인, 측정 가능한 완료 기준, 수집원·라이브러리·위험요소 보완 |
| v1.4 | 2026-11-23 | 원이대로(명곡교→가음정사거리, W0~W5) 예측 대상 추가(R-09), 도로 구분 `road_name`·`settings.corridors/target_corridors`, 3.4 방향 조건 도로별 |
| v1.3 | 2026-11-18 | 표준노드링크(R-03b) 기준 분석 구간을 6개(S1~S6)+참고 S0로 확정, 본선 판정 규칙 |
| v1.2 | 2026-11-18 | 시민 공개 서비스(Phase 2) 추가: FR-013·014, 20장 신설, 혼잡 등급 적중률 지표, 발행 모듈·정적 웹 폴더, 공개 관련 보안·위험·테스트·일정 |

---

# 0. 용어 정의

| 용어 | 정의 |
|---|---|
| 링크(link) | 수집원(표준노드링크 등)이 정의한 최소 도로 단위. 방향별로 별도 ID를 가진다. |
| 구간(segment) | 본 프로젝트가 정의한 분석 단위. 1개 이상의 링크로 구성된다. |
| bin | 5분 단위 시간 구간. `bin_time`은 구간의 **시작 시각**으로 표기한다. 예: 07:00 bin = [07:00, 07:05) |
| 기준 시각(base_time) | 예측 시 사용 가능한 최신 bin의 시각. 예측 입력은 이 시각까지의 데이터만 사용한다. |
| horizon | 기준 시각으로부터 예측 대상 시각까지의 시간(분). 5, 10, 15, 30 |
| 대상 시각(target_time) | base_time + horizon |
| 수집 시각(collected_at) | 시스템이 데이터를 실제로 받은 시각 |
| 원본 시각(source_timestamp) | 수집원이 데이터에 붙인 관측·갱신 시각 |

모든 시각은 **KST(UTC+09:00)** 기준이다.

---

# 1. 프로젝트 개요

## 1.1 프로젝트 목적

창원시 창원대로의 평일 아침 출근 시간대 교통 데이터를 수집하고, 머신러닝 모델을 이용해 도로 구간별 미래 교통 흐름을 예측하는 시스템을 개발한다.

현재 교통 상태를 단순히 조회하는 수준을 넘어, 현재까지 수집된 교통 데이터를 바탕으로 향후 5~30분의 평균 속도 변화를 예측하는 것을 목적으로 한다. 교통량은 실제 데이터가 확보되는 경우에 한해 예측 대상에 포함한다.

초기 개발은 로컬 PC에서 실행하는 Python 프로그램으로 진행하며, 공공 교통정보 API를 통해 데이터를 수집하고 SQLite에 저장한다.

## 1.2 프로젝트 핵심 목표

1. 창원대로 교통정보 자동 수집 (평일 아침 출근 시간대 중심)
2. 도로 구간별 교통 데이터 저장 및 분석
3. 5분, 10분, 15분, 30분 후 평균 속도 예측
4. 교통량 데이터 확보 시 미래 교통량 예측 기능 추가 (조건부)
5. 실제 교통 데이터와 예측 결과 비교
6. 기준 모델 대비 예측 모델의 정확도 및 성능 평가
7. 검증된 예측 결과를 일반 시민이 볼 수 있는 모바일 웹으로 공개 (Phase 2, 20장)

## 1.3 프로젝트 범위

| 구분 | 정의 |
|---|---|
| 대상 도로 | 창원대로 |
| 진행 방향 | 팔용동 → 성산구·산업단지 (창원터널 방면) |
| 분석 요일 | 평일(월~금), 공휴일 제외 |
| 분석 시간 | 예측 대상 시각(target_time) 기준 07:00~09:00 |
| 데이터 수집 | 상시(24시간) 자동 수집, 호출 제한 시 평일 06:00~10:00 최소 수집 |
| 데이터 기본 단위 | 5분 |
| 예측 시간 | 5분, 10분, 15분, 30분 후 |
| 주요 예측값 | 평균 속도 (교통량은 조건부) |
| 개발 언어 | Python |
| 데이터베이스 | SQLite |
| 머신러닝 | XGBoost |
| 시각화 | Streamlit, Plotly (내부 대시보드) |
| 시민 공개 | 정적 모바일 웹 + 외부 정적 호스팅 (Phase 2, 20장) |

---

# 2. 시스템 개발 범위

## 2.1 MVP 개발 범위

| ID | 기능 | 우선순위 | 인수 기준 | 관련 테스트 |
|---|---|---|---|---|
| FR-001 | 교통정보 API 연동 | 필수 | 인증 후 대상 링크 전체의 응답을 파싱할 수 있다 | T-COL-01~03 |
| FR-002 | 도로 구간별 교통정보 수집 | 필수 | `segment_link`의 모든 활성 링크에 대해 수집을 시도하고, 링크별 성공·실패를 기록한다 | T-COL-04~06 |
| FR-003 | 수집 데이터 SQLite 저장 | 필수 | 동일 (source, link_id, source_timestamp)는 1건만 저장된다 | T-COL-07, T-PRC-01 |
| FR-004 | 데이터 결측 및 이상치 처리 | 필수 | 6.3·6.4의 규칙대로 플래그가 부여되고, 결측이 0으로 변환되지 않는다 | T-PRC-02~05 |
| FR-005 | 구간별 5분 시계열 생성 | 필수 | `segment_traffic_5min`이 6.2의 집계 규칙으로 생성되고 품질 지표가 함께 저장된다 | T-PRC-06~08 |
| FR-006 | XGBoost 예측 모델 학습 | 필수 | horizon별 모델이 학습되고 `model_registry`에 이력이 저장된다 | T-PRD-01 |
| FR-007 | 미래 평균 속도 예측 | 필수 | 수집 완료 후 매 5분 자동 예측되어 `traffic_prediction`에 저장된다 | T-PRD-02~03 |
| FR-008 | 예측 결과와 실제값 비교 | 필수 | 대상 시각의 실제값이 확보되면 오차가 계산된다 | T-PRD-04 |
| FR-009 | 예측 성능 평가 | 필수 | 8장의 지표·기준 모델 비교 결과가 `model_evaluation`에 저장된다 | T-PRD-05~06 |
| FR-010 | 교통 흐름 대시보드 | 필수 | 9장의 항목이 표시되고 데이터 지연이 표시된다 | T-DSH-01~03 |
| FR-011 | 미래 교통량 예측 | 데이터 확보 시 | 실제 교통량 레이블이 있을 때만 학습한다 | - |
| FR-012 | CCTV 영상 차량 검출 | 후속 개발 | - | - |

## 2.2 Phase 2 개발 범위 (시민 공개)

Phase 1 정식 평가 후 공개 조건(PRD 8.2)을 충족하면 개발·공개한다. 세부 명세는 20장을 따른다.

| ID | 기능 | 우선순위 | 인수 기준 | 관련 테스트 |
|---|---|---|---|---|
| FR-013 | 시민 공개 모바일 웹 페이지 | Phase 2 필수 | 20.4의 화면과 20.5의 표시 규칙대로 동작한다 | T-PUB-01~06 |
| FR-014 | 공개용 결과 발행 | Phase 2 필수 | 예측 저장 후 1분 이내에 공개 JSON이 외부 호스팅에 반영되고, 실패 시 기록·경고된다 | T-PUB-07~10 |

## 2.3 개발 제외 범위

다음 기능은 개발하지 않는다.

- 네이티브 모바일 애플리케이션 (Phase 2는 모바일 웹으로 제공)
- 사용자 회원가입, 로그인, 알림
- 수집·학습·예측의 클라우드 이전 (Phase 2에서도 로컬 PC에서 수행하고, 공개용 결과 파일만 외부 정적 호스팅에 발행)
- 외부 개발자용 공개 API (10장은 향후 확장을 위한 참고용)
- 실시간 교통 신호 제어
- 자율주행 및 차량 경로 최적화
- CCTV 영상 기반 차량 추적
- 창원시 전체 도로망 예측
- 교통사고 발생 가능성 예측

---

# 3. 대상 도로 및 구간 정의

## 3.1 대상 도로 개요

창원대로는 의창구 소계동 소계광장 교차로에서 성산구 불모산동 창원터널까지 이어지는 간선도로다(총연장 약 14.9km). 이 중 삼정자동~창원터널 구간은 자동차전용도로로 성격이 다르므로 분석 범위에서 제외한다.

팔용동에서 성산구 및 산업단지 방향으로 이동하는 출근 차량 흐름을 분석한다. 분석 범위는 **팔용사거리 ~ 성주광장**으로 한다(상류 참고 구간 S0 포함 시 소계광장교차로부터).

**원이대로** (v1.4 추가): 의창구 도계동 도계광장교차로에서 성산구 가음정동 가음정사거리까지 이어지는 시도다. 분석 범위는 **명곡교 ~ 가음정사거리**(약 7.1km, 출근 방향 남하)로 하고 상류 참고 구간 W0(목련삼거리~명곡교)를 둔다. 끝 지점 가음정사거리는 창원대로 S5/S6 경계와 같은 교차로다. 시간대는 창원대로와 같다.

도로는 `road_segment.road_name`으로 구분하고, 도로 목록·표시 순서는 `settings.corridors`, 예측 대상 도로는 `settings.target_corridors`로 정한다. 수집 성공률·평가 집계·대시보드는 도로별로 본다.

## 3.2 구간 분할 원칙

1. 구간 경계는 주요 교차로(간선도로 교차점) 또는 지하차도 시·종점에 둔다.
2. 구간 길이는 가능한 한 **1~2.5km 범위로 균등**하게 맞춘다. 표준노드링크의 링크 길이를 확인한 후 조정한다.
3. 지하차도가 있는 교차로는 **본선(지하차도) 링크와 지상 측도 링크를 구분해 저장**하고, 구간 대표값은 본선 기준으로 산출한다. 측도 값은 별도 특성으로 활용을 검토한다.
4. 구간 수는 고정하지 않는다. 링크 확인 결과에 따라 병합·분할할 수 있으며, 변경 시 `segment_link.valid_from/valid_to`로 이력을 관리한다.

## 3.3 분석 구간 (v1.3 확정, 표준노드링크 2026-11-11 배포본 기준)

| 구간 ID | 시작 지점 | 종료 지점 | 경유 주요 교차로 | 본선 길이 | 비고 |
|---|---|---|---|---|---|
| S0 | 소계광장교차로 | 팔용사거리 | - | 530m | 상류 참고 구간(예측 대상 아님, 입력 특성용) |
| S1 | 팔용사거리 | 차룡사거리 | 반계사거리, 평산사거리, 죽전사거리, 죽전삼거리 | 1,844m | |
| S2 | 차룡사거리 | 용원지하차도(서측) | 사화사거리, 터미널사거리 | 1,694m | 종합버스터미널 진출입 |
| S3 | 용원지하차도(서측) | 삼동지하차도(동측) | 용원교차로, 창원천교, 삼동교차로 | 1,884m | 용원·삼동 지하차도(본선·측도 쌍 포함) |
| S4 | 삼동지하차도(동측) | 공단본부삼거리 | 교육단지사거리, 창원병원사거리 | 1,591m | 산업단지 진입 시작 |
| S5 | 공단본부삼거리 | 가음정사거리 | 재료연구소삼거리, 남고삼거리, 성산패총사거리 | 2,053m | 산업단지 |
| S6 | 가음정사거리 | 성주광장 | 남산삼거리 | 1,167m | 성주지하차도 일부, 하류 끝 |

- 근거: `docs/research/R-03b-changwondaero-links.md`, 링크 표 `config/segment_links.csv`(86개 링크, 원본 `docs/research/samples/changwondaero_links_2026-11-11.csv`).
- 경계는 교차로 진입 노드 또는 지하차도 분기점이다. 교차로 내부의 짧은 링크(약 12m)는 하류 구간에 넣는다.
- 본선 판정은 지하차도 구간에서 `ROAD_TYPE='002'`(지하차도) 링크를 본선(`is_mainline=1`), 같은 구간의 평면 링크를 측도(0)로 둔다.
- v1.2의 8구간 후보(S0~S7)는 S1(693m)·S5(745m)가 짧고 S4(2,730m)가 길어 3.2 원칙 2에 맞지 않아 재편했다.

### 원이대로 (v1.4, 명곡교 → 가음정사거리)

| 구간 ID | 시작 지점 | 종료 지점 | 경유 주요 교차로 | 본선 길이 | 비고 |
|---|---|---|---|---|---|
| W0 | 목련삼거리 | 명곡교(서측) | 명서사거리 | 744m | 상류 참고 구간(예측 대상 아님, 입력 특성용) |
| W1 | 명곡교(서측) | 중앙중사거리 | 상북사거리, 명곡광장교차로, 시티세븐교차로 | 1,532m | 명곡교·창원천3교 교량 포함, 창이대로 평면 교차 |
| W2 | 중앙중사거리 | 용지사거리 | 운동장사거리, 경륜장삼거리 | 1,504m | |
| W3 | 용지사거리 | 한국은행사거리 | 시청사거리, 창원광장(로터리) | 1,000m | 로터리 통과부 ~250m는 원이대로 명칭 링크가 없어 ITS 관측 없음. `distance_m`은 관측 링크 합 기준(실도로 약 1,250m) |
| W4 | 한국은행사거리 | 성원아파트사거리 | 토월중학교삼거리, 생활체육관삼거리, 상남사거리 | 1,311m | |
| W5 | 성원아파트사거리 | 가음정사거리 | 남양삼거리, 가음정삼거리, 장미공원사거리 | 1,477m | 가음정교 교량 포함 |

- 근거: `docs/research/R-09-wonidaero-links.md`, 링크 행 `docs/research/samples/wonidaero_segment_links_candidates_2026-11-23.csv`(35행) → `config/segment_links.csv`.
- 지하차도가 없어 `is_mainline`은 모두 1. 배포본에 없는 ITS 구 ID 3개는 그 ID를 쓰고 길이는 대응 배포본 구간 합을 배분했다(R-09).

## 3.4 도로 구간 확정 조건

각 구간은 다음 조건을 만족해야 한다.

1. 대상 도로(3.1)에 포함되는 도로 링크일 것
2. 각 도로의 분석 방향과 일치할 것 — 창원대로: 팔용동 → 창원터널 방면, 원이대로: 명곡교 → 가음정사거리 방면 (링크의 시작·종료 노드로 확인)
3. API에서 식별할 수 있는 고유 링크 ID가 존재할 것
4. 구간별 평균 속도 또는 소통정보를 수집할 수 있을 것
5. 동일 구간의 과거 데이터와 현재 데이터를 연결할 수 있을 것
6. 구간 내 링크 길이 합이 확인될 것

## 3.5 도로 링크 매핑

실제 API의 링크 ID를 분석 구간에 매핑하는 `segment_link` 테이블(5.2)을 구성한다. 구간과 링크는 **1:N** 관계다.

예시:

| segment_id | seq | link_id | link_length(m) | is_mainline | description |
|---|---|---|---|---|---|
| S1 | 1 | API 확인 후 입력 | 확인 후 입력 | 1 | 팔용사거리~반계사거리 |
| S1 | 2 | API 확인 후 입력 | 확인 후 입력 | 1 | 반계사거리~평산사거리 |
| S4 | 1 | API 확인 후 입력 | 확인 후 입력 | 1 | 용원지하차도 본선 |
| S4 | 2 | API 확인 후 입력 | 확인 후 입력 | 0 | 용원교차로 지상 측도 |

링크별 데이터를 먼저 저장하고, 구간별 대표값은 6.2의 규칙으로 별도 산출한다. 링크 매핑 정보의 단일 원본(source of truth)은 DB의 `segment_link` 테이블이며, `config/segments.py`는 초기 적재용 시드 데이터로만 사용한다.

---

# 4. 데이터 수집 명세

## 4.1 데이터 수집원

### ① 경찰청 교통소통정보 서비스 (UTIC 데이터, 공공데이터포털)

- 도시교통정보센터(UTIC)가 수집한 전국 실시간 소통정보
- 국토교통부 표준노드링크 기준, XML 형식
- **인증키 + IP 인증 필요**, 개발 단계 자동승인 / 운영 단계 심의승인
- 공공데이터포털: https://www.data.go.kr/data/15087120/openapi.do
- 도시교통정보센터: https://www.utic.go.kr/

### ② ITS 국가교통정보센터

- 표준노드링크 기준 링크별 소통정보(5분 간격 통행속도) Open API
- 표준노드링크 SHP 파일(링크 길이, 노드 위치, 방향) 제공 → 구간 매핑의 기준 자료
- https://www.its.go.kr/

### ③ 창원시 교통정보센터(UTIS)

- 실시간 도로 소통정보, 구간 속도, 지·정체 상태, CCTV
- https://utis.changwon.go.kr/
- 공식 Open API 제공 여부를 확인한다. **공식 API가 없으면 웹 화면 스크레이핑은 이용약관 확인 및 기관 승인 전에는 사용하지 않는다.** 대신 표출 구간명·속도를 수집 데이터 교차 검증용으로 참고한다.

### ④ 보조 데이터

| 데이터 | 수집원 후보 |
|---|---|
| 기상(강수량, 기온) | 기상청 초단기실황 API (공공데이터포털) |
| 공휴일·대체공휴일 | 한국천문연구원 특일정보 API 또는 `holidays` 패키지 |
| 학교 방학 기간 | 경상남도교육청 학사일정 (수동 입력) |
| 산업단지 집단휴가 기간 | 수동 입력 |
| 사고·공사 정보 | UTIC 돌발정보 |

## 4.2 데이터 연동 원칙

실제 API 응답 스키마, 창원대로 링크 ID, 갱신 주기 및 호출 제한은 아직 확정되지 않았다. 다음 항목을 먼저 확인한 후 수집기를 구현한다.

| 확인 항목 | 내용 |
|---|---|
| API URL | 실제 호출 주소 |
| 인증 방식 | API Key, IP 인증 여부 |
| 응답 형식 | JSON 또는 XML |
| 도로 식별자 | Link ID (표준노드링크 버전 포함) |
| 속도 필드 | 평균 속도 또는 구간 속도, 단위 |
| 통행시간 필드 | 제공 여부, 단위 |
| 교통량 필드 | 차량 대수 및 집계 기준 |
| 소통 상태 코드 | 코드값과 의미 |
| 데이터 시각 | 관측 시각 또는 갱신 시각 |
| 갱신 주기 | 실제 데이터 업데이트 간격 |
| 호출 제한 | 초당 및 일일 호출 가능 횟수 |
| 결측·기본값 표현 | 0, -1, 빈 값 등 결측을 나타내는 방식 |

실제 제공되지 않는 필드는 임의로 생성하지 않는다. 원본 값에서 계산한 파생값(예: 속도 기반 혼잡 등급)은 파생값임을 컬럼명 또는 플래그로 구분한다.

## 4.3 수집 데이터 항목 (링크 단위 원본)

| 필드 | 자료형 | 설명 |
|---|---|---|
| collected_at | TEXT(ISO8601) | 시스템 수집 시각 |
| source_timestamp | TEXT(ISO8601) | 원본 데이터 기준 시각 |
| source | TEXT | 데이터 제공처 |
| link_id | TEXT | 원본 도로 링크 ID |
| speed | REAL | 평균 속도(km/h) |
| travel_time | REAL | 통행시간(초), 제공 시 |
| volume | INTEGER | 교통량, 제공 시 |
| congestion_code | TEXT | 원본 소통 상태 코드 |
| raw_file | TEXT | 원본 응답 파일 경로 (`data/raw/`) |

구간 ID와 진행 방향은 원본에 저장하지 않고 `segment_link` 매핑으로 결정한다. 교통량의 단위는 원본 API의 집계 기준(5분간 대수/시간당 환산 등)을 확인한 후 확정한다.

원본 응답은 `data/raw/{source}/{YYYYMMDD}/{HHMMSS}.xml` 형태로 압축 보관해 파싱 오류 시 재처리할 수 있도록 한다.

## 4.4 수집 주기 및 기간

- 기본 분석 단위: 5분
- 수집 주기: API 갱신 주기와 호출 제한을 고려해 설정 (갱신 주기가 5분이면 1~2분 간격으로 조회하고 신규 데이터만 저장)
- 수집 시간: **상시(24시간)** 수집을 기본으로 한다. 호출 제한으로 불가능하면 **평일 06:00~10:00**을 최소 수집 시간으로 한다.
- 주요 분석 시간: 예측 대상 시각 07:00~09:00
- 수집 기간: 파이프라인 시험은 수집 2주 시점에 수행하고, **정식 모델 평가는 최소 8주(평일 약 40일), 권장 12주 이상** 축적 후 수행한다.

06:00부터 수집하는 이유는 07:00 대상 예측(base_time 06:30, 30분 후)에 필요한 과거 30분 이상의 입력을 확보하기 위해서다. 출근 시간 외 데이터는 모델의 일반 패턴 학습과 기준 모델 산출에 보조적으로 활용한다.

수집 프로그램은 원본 시각을 확인해 동일한 원본 데이터가 반복 저장되지 않도록 처리한다.

## 4.5 데이터 수집 실패 처리

| 상황 | 처리 |
|---|---|
| API 응답 지연 | 타임아웃(10초) 후 지수 백오프 재시도(최대 3회) |
| API 호출 실패 | 재시도 후 실패 시 `collection_log`에 `failed` 기록, 다음 주기 정상 진행 |
| 인증키·IP 인증 오류 | 즉시 `auth_error` 기록, 재시도하지 않음, 로그 경고 |
| 응답 데이터 일부 누락 | 수신된 링크만 저장, `partial` 기록, 누락 링크 수 기록 |
| 도로 링크 ID 불일치 | 저장하지 않고 경고 로그 (표준노드링크 버전 변경 가능성 확인) |
| 속도 값 이상 | 원본은 저장하고 `quality_flag` 부여 (6.4) |
| 동일 시각 데이터 중복 | UNIQUE 제약으로 무시 (INSERT OR IGNORE) |

수집 실패를 실제 교통량 0 또는 속도 0으로 변환하지 않는다.

## 4.6 수집 실행 및 운영

- 수집기는 APScheduler 기반 상주 프로세스로 실행하고, **Windows 작업 스케줄러**에 로그온/부팅 시 자동 시작으로 등록한다.
- 수집 PC는 절전·최대 절전 모드를 해제하고, Windows 업데이트 재시작 시간을 수집 시간 외로 설정한다.
- 시스템 시각은 NTP로 동기화되어 있어야 한다.
- 수집 공백(PC 중단 등)은 `collection_log`로 사후 확인 가능해야 하며, 공백 기간은 결측으로 처리한다.

---

# 5. 데이터베이스 설계

## 5.1 공통 규칙

- SQLite를 사용하며 **WAL 모드**(`PRAGMA journal_mode=WAL`)로 운영해 수집기 쓰기와 대시보드 읽기를 병행한다.
- 시각은 `YYYY-MM-DDTHH:MM:SS+09:00` 형식의 ISO8601 TEXT로 저장한다.
- BOOLEAN은 INTEGER(0/1)로 저장한다.
- 외래 키 제약을 활성화한다(`PRAGMA foreign_keys=ON`).
- DB 파일은 매일 1회 백업한다(최근 14일 보관).

## 5.2 road_segment / segment_link

```sql
CREATE TABLE road_segment (
    segment_id     TEXT PRIMARY KEY,          -- S0 ~ S6
    road_name      TEXT NOT NULL,             -- 창원대로
    start_node     TEXT NOT NULL,
    end_node       TEXT NOT NULL,
    direction      TEXT NOT NULL,             -- 팔용동→창원터널 방면
    seq            INTEGER NOT NULL,          -- 상류→하류 순서
    distance_m     REAL,                      -- 본선 링크 길이 합
    is_target      INTEGER NOT NULL DEFAULT 1,-- 예측 대상 여부 (S0=0)
    is_active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE segment_link (
    id             INTEGER PRIMARY KEY,
    segment_id     TEXT NOT NULL REFERENCES road_segment(segment_id),
    link_id        TEXT NOT NULL,
    source         TEXT NOT NULL,
    seq            INTEGER NOT NULL,          -- 구간 내 링크 순서
    link_length_m  REAL,
    is_mainline    INTEGER NOT NULL DEFAULT 1,-- 0: 지하차도 지상 측도 등
    nodelink_ver   TEXT,                      -- 표준노드링크 버전
    valid_from     TEXT NOT NULL,
    valid_to       TEXT,                      -- NULL = 현재 유효
    UNIQUE (source, link_id, valid_from)
);
```

## 5.3 traffic_observation (링크 단위 원본)

```sql
CREATE TABLE traffic_observation (
    id               INTEGER PRIMARY KEY,
    source           TEXT NOT NULL,
    link_id          TEXT NOT NULL,
    source_timestamp TEXT NOT NULL,
    collected_at     TEXT NOT NULL,
    speed            REAL,
    travel_time      REAL,
    volume           INTEGER,
    congestion_code  TEXT,
    quality_flag     TEXT NOT NULL DEFAULT 'ok', -- ok / out_of_range / frozen / default_value
    raw_file         TEXT,
    UNIQUE (source, link_id, source_timestamp)
);
CREATE INDEX ix_obs_link_time ON traffic_observation (link_id, source_timestamp);
```

## 5.4 segment_traffic_5min (구간 단위 전처리)

```sql
CREATE TABLE segment_traffic_5min (
    segment_id        TEXT NOT NULL REFERENCES road_segment(segment_id),
    bin_time          TEXT NOT NULL,          -- bin 시작 시각
    available_at      TEXT NOT NULL,          -- 이 값의 근거 데이터 중 가장 늦은 collected_at
    speed             REAL,                   -- 거리 가중 조화평균 (6.2)
    speed_side        REAL,                   -- 지상 측도 속도 (해당 시)
    volume            REAL,
    n_links_expected  INTEGER NOT NULL,
    n_links_observed  INTEGER NOT NULL,
    is_imputed        INTEGER NOT NULL DEFAULT 0,
    quality_flag      TEXT NOT NULL,          -- ok / partial / imputed / missing
    processed_at      TEXT NOT NULL,
    PRIMARY KEY (segment_id, bin_time)
);
```

## 5.5 traffic_prediction

```sql
CREATE TABLE traffic_prediction (
    id               INTEGER PRIMARY KEY,
    segment_id       TEXT NOT NULL REFERENCES road_segment(segment_id),
    base_time        TEXT NOT NULL,           -- 입력 데이터 기준 시각
    executed_at      TEXT NOT NULL,           -- 예측 실행 시각
    horizon          INTEGER NOT NULL,        -- 5/10/15/30
    target_time      TEXT NOT NULL,
    target_var       TEXT NOT NULL,           -- speed / volume
    predicted_value  REAL,
    model_version    TEXT NOT NULL REFERENCES model_registry(model_version),
    input_quality    TEXT NOT NULL,           -- ok / degraded / skipped
    actual_value     REAL,                    -- 대상 시각 실제값 (사후 갱신)
    abs_error        REAL,                    -- 사후 갱신
    UNIQUE (segment_id, base_time, horizon, target_var, model_version)
);
```

기준 모델(8.2)의 예측도 같은 테이블에 `model_version='baseline_persistence'` 등으로 저장해 동일한 방식으로 비교한다.

## 5.6 model_registry / model_evaluation

```sql
CREATE TABLE model_registry (
    model_version   TEXT PRIMARY KEY,         -- 예: xgb_speed_h15_20270115
    model_type      TEXT NOT NULL,            -- xgboost / baseline_*
    target_var      TEXT NOT NULL,
    horizon         INTEGER NOT NULL,
    train_start     TEXT,
    train_end       TEXT,
    features        TEXT,                     -- JSON 배열
    hyperparams     TEXT,                     -- JSON
    artifact_path   TEXT,                     -- saved_models/ 경로
    trained_at      TEXT NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE model_evaluation (
    id              INTEGER PRIMARY KEY,
    model_version   TEXT NOT NULL REFERENCES model_registry(model_version),
    eval_type       TEXT NOT NULL,            -- validation / test / walk_forward / live
    period_start    TEXT NOT NULL,
    period_end      TEXT NOT NULL,
    segment_id      TEXT,                     -- NULL = 전체
    regime          TEXT,                     -- all / congestion_onset / congested / free_flow
    n_samples       INTEGER NOT NULL,
    mae             REAL,
    rmse            REAL,
    wape            REAL,
    grade_accuracy  REAL,                     -- 혼잡 등급 적중률 (8.1)
    evaluated_at    TEXT NOT NULL
);
```

## 5.7 collection_log

```sql
CREATE TABLE collection_log (
    id              INTEGER PRIMARY KEY,
    source          TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT NOT NULL,            -- success / partial / failed / auth_error / no_update
    http_status     INTEGER,
    links_expected  INTEGER,
    links_received  INTEGER,
    record_count    INTEGER,                  -- 신규 저장 건수
    error_message   TEXT
);
```

## 5.8 calendar_info

```sql
CREATE TABLE calendar_info (
    date              TEXT PRIMARY KEY,       -- YYYY-MM-DD
    is_holiday        INTEGER NOT NULL,       -- 공휴일·대체공휴일
    holiday_name      TEXT,
    is_school_vacation INTEGER NOT NULL DEFAULT 0,
    is_industrial_vacation INTEGER NOT NULL DEFAULT 0,
    is_holiday_adjacent INTEGER NOT NULL DEFAULT 0 -- 명절·연휴 전후 평일
);
```

---

# 6. 데이터 전처리

## 6.1 처리 순서

1. 원본 시각 기준 정렬
2. 중복 데이터 제거
3. 시각 KST 정규화 및 5분 bin 할당 (`source_timestamp` 기준, bin 시작 시각으로 내림)
4. 링크 ID와 분석 구간 매핑 (해당 시점에 유효한 `segment_link` 사용)
5. 이상치 판정 및 플래그 부여 (6.4)
6. 구간별 5분 집계 (6.2)
7. 결측 처리 (6.3)
8. 분석용 시계열·특성 생성 (6.5, 6.6)

## 6.2 5분 단위 구간 집계

**링크 → bin**: 한 bin에 같은 링크의 값이 여러 개면 원본 시각이 가장 늦은 값을 사용한다.

**링크 → 구간 속도**: 구간 대표 속도는 본선 링크(`is_mainline=1`)의 **거리 가중 조화평균**으로 계산한다.

```
segment_speed = Σ(link_length) / Σ(link_length / link_speed)
```

이는 구간 전체 통행시간 기준의 평균 속도와 일치한다. 링크 길이가 확인되지 않은 경우에 한해 단순 평균을 임시로 사용하고 `quality_flag`에 기록한다.

**부분 관측**: 구간 링크 길이 합의 70% 이상이 관측되면 관측된 링크만으로 산출하고 `partial`로 표시한다. 70% 미만이면 `missing`으로 처리한다.

**교통량**: 실제 집계 구간과 단위를 유지한다. 서로 다른 링크의 교통량은 합산하지 않고, 구간 대표 지점(예: 구간 마지막 링크) 값을 사용한다.

**available_at**: 각 bin 값의 근거가 된 원본 중 가장 늦은 `collected_at`을 저장한다. 예측 시 이 값을 기준으로 사용 가능 여부를 판단한다(6.6).

## 6.3 결측 처리

- 실제 교통량 0과 측정 누락을 구분한다.
- 누락 데이터를 0으로 변환하지 않는다.
- **짧은 결측**: 연속 2개 bin(10분) 이하 → **직전 관측값으로 채움(forward fill)**, `is_imputed=1`
- **장시간 결측**: 연속 3개 bin 이상 → 채우지 않고 `missing` 유지
- **선형 보간 등 결측 이후의 값을 사용하는 방법은 사용하지 않는다.** 실시간 예측에서는 미래 값을 알 수 없으므로 학습과 예측에 같은 규칙을 적용한다.
- 예측 입력 중 현재값 또는 lag 특성의 50% 이상이 결측이면 해당 예측을 보류(`input_quality='skipped'`)하고, 일부 결측이면 `degraded`로 표시한 후 예측한다(XGBoost 결측 처리 사용).
- 학습 데이터에서는 `is_imputed=1`인 bin을 예측 대상(레이블)으로 사용하지 않는다.

## 6.4 이상치 기준

| 유형 | 기준 | 처리 |
|---|---|---|
| 범위 이탈 | speed < 0 또는 speed > 제한속도 × 1.5 | `out_of_range`, 집계 제외 |
| 기본값 | API 문서상 결측 기본값(0, -1, 999 등) | `default_value`, 결측 처리 |
| 0 속도 | speed = 0 | 결측 표현인지 실제 정지인지 API 문서로 확인 후 규칙 확정. 확정 전에는 `default_value`로 처리 |
| 갱신 정지 | 동일 링크의 값이 6회(30분) 이상 완전히 동일하고 원본 시각만 갱신 | `frozen`, 집계 제외 |

제한속도는 링크별로 `segment_link`(또는 표준노드링크 속성)에서 가져온다. 기준값은 데이터 축적 후 분포를 확인해 v1.2에서 재조정한다.

## 6.5 시간·달력 특성

- hour, minute → 하루 중 분(minute_of_day)과 sin/cos 변환
- day_of_week → sin/cos 변환 또는 범주형
- is_holiday_adjacent (명절·연휴 전후 평일)
- is_school_vacation
- is_industrial_vacation

분석 대상이 평일(공휴일 제외)이므로 `is_weekend`, 평일 여부, `is_holiday`는 학습 데이터 내에서 상수가 되어 특성으로 사용하지 않는다. 공휴일은 학습·평가 대상에서 제외하고, 상시 수집 데이터를 활용하는 보조 모델에서만 사용을 검토한다. 출근 시간대 여부도 분석 시간이 출근 시간대로 한정되므로 사용하지 않는다.

## 6.6 미래 정보 누출 방지 규칙

1. 기준 시각 t의 예측 입력은 `available_at ≤ t`인 데이터만 사용한다(as-of 조인).
2. 학습 데이터 생성 시에도 동일한 as-of 규칙을 적용해 실시간 예측 환경과 일치시킨다.
3. "과거 동일 요일·시간대 평균" 등 통계 특성은 학습 기간 데이터만으로 계산한다.
4. 스케일링·인코딩이 필요한 경우 학습 기간으로만 fit한다.

---

# 7. 머신러닝 예측 모델

## 7.1 초기 모델

XGBoost Regressor를 사용한다.

선정 이유:

- 표 형태의 시계열 특성 데이터에 적용하기 용이
- 비선형적인 교통 패턴 학습 가능
- 적은 규모의 데이터에서도 기준 모델을 만들기 쉬움
- 결측값을 자체 처리
- 특성 중요도 분석 가능

단, XGBoost가 다른 모델보다 우수하다고 미리 가정하지 않는다. 기준 모델과 비교해 성능을 검증한다.

## 7.2 예측 목표

| 예측 대상 | 예측 시점 | 조건 |
|---|---|---|
| 평균 속도 | 5, 10, 15, 30분 후 | 필수 |
| 교통량 | 5, 10, 15, 30분 후 | 실제 교통량 레이블 확보 시 |

예측 대상 구간은 `is_target=1`인 구간(S1~S6)이다. S0는 입력 특성으로만 사용한다.

모델의 학습 목표는 **속도 변화량(target_speed − current_speed)** 과 **절대 속도** 두 방식을 비교하고, 검증 성능이 좋은 방식을 채택한다. 출력은 항상 절대 속도로 변환해 저장한다.

## 7.3 입력 특성

### 현재 및 과거 교통정보 (해당 구간)

- 현재 평균 속도
- 5, 10, 15, 30분 전 속도
- 최근 15분, 30분 평균 속도
- 최근 5분, 15분 속도 변화량
- 현재 bin의 품질 플래그 (imputed 여부)

### 인접 구간 정보

- 상류(이전) 구간 현재 속도 및 변화량
- 하류(다음) 구간 현재 속도 및 변화량 (정체 역류 신호)
- 하류 2개 구간까지의 속도
- 지하차도 구간의 경우 측도 속도

S1의 상류는 S0를 사용한다. S6의 하류는 없으므로 결측(NaN)으로 두고 XGBoost 결측 처리에 맡긴다.

### 시간·달력 특성

- 6.5의 특성

### 과거 패턴 특성

- 과거 동일 요일·동일 bin의 평균 속도 (학습 기간 기준, 최소 3주 이상 데이터가 있을 때)

### 추가 특성 (데이터 확보 시)

- 교통량
- 강수량, 기온
- 사고 및 공사 정보

## 7.4 모델 구성

**방식 A: 통합 모델 (기본)**

모든 예측 대상 구간을 하나의 학습 데이터셋으로 구성하고 `segment_id`를 범주형 특성으로 사용한다(XGBoost `enable_categorical=True`).

**방식 B: 구간별 모델**

각 구간마다 독립적인 모델을 학습한다. 충분한 데이터(12주 이상)가 축적되면 방식 A와 성능을 비교한다.

예측 horizon별로 독립 모델을 학습한다(속도 기준 4개 모델).

## 7.5 학습 절차

- 하이퍼파라미터는 시계열 분할 교차검증(`TimeSeriesSplit`, 일 단위 분할)으로 탐색한다. 탐색 범위: `max_depth`, `learning_rate`, `n_estimators`(early stopping), `min_child_weight`, `subsample`.
- 학습 결과는 `saved_models/`에 저장하고 `model_registry`에 등록한다.
- 재학습 주기: 주 1회(주말), 최신 데이터 포함 재학습. 새 모델은 직전 4주 walk-forward 성능이 기존 모델보다 좋을 때만 `is_active=1`로 교체한다.

## 7.6 예측 실행 파이프라인

```
[매 5분, 수집 완료 직후]
  1. 신규 원본 → segment_traffic_5min 갱신
  2. base_time = 사용 가능한 최신 bin
  3. 활성 모델 + 기준 모델로 horizon별 예측 → traffic_prediction 저장
  4. target_time이 도래한 과거 예측에 actual_value, abs_error 갱신
```

- 예측은 수집 시간 내 상시 실행하되, 평가는 target_time 07:00~09:00만 대상으로 한다.
- 수집 데이터가 10분 이상 지연되면 예측을 보류하고 상태를 기록한다.
- 수집 프로세스와 학습 프로세스는 분리한다. 학습은 별도 명령으로 실행한다.

---

# 8. 모델 평가 기준

## 8.1 평가 지표

| 지표 | 목적 |
|---|---|
| MAE | 평균 예측 오차 (주 지표) |
| RMSE | 큰 예측 오차에 대한 민감도 |
| WAPE | 실제값 규모 대비 전체 오차 |

교통량에 0이 포함될 수 있으므로 MAPE를 주 평가 지표로 사용하지 않는다.

**보조 지표 — 혼잡 등급 적중률**: 예측 속도와 실제 속도를 9.2의 혼잡 등급으로 변환해 일치 비율을 계산한다. 시민 공개 화면의 정확도 안내(20.4)에 사용하므로, 등급 경계는 내부 대시보드와 공개 화면에서 동일한 값을 사용한다. 등급별 정밀도·재현율(특히 "정체" 등급)도 함께 산출한다. `model_evaluation`에 `grade_accuracy` 컬럼으로 저장한다.

지표는 다음 단위로 각각 산출한다.

- horizon별
- 구간별
- 교통 상태별: 원활(free_flow), **정체 시작(congestion_onset, 15분 내 속도 30% 이상 하락)**, 정체(congested)

정체 시작 구간의 오차는 실사용 가치가 가장 크므로 별도로 보고한다.

## 8.2 기준 모델 비교

XGBoost 성능은 다음 기준 모델과 비교한다.

1. 현재 속도 유지 모델 (persistence)
2. 최근 15분 평균 속도 모델
3. 과거 동일 요일·시간대 평균 모델 (학습 기간 3주 이상 확보 시)

## 8.3 데이터 분리

시간 순서를 유지해 학습 및 평가 데이터를 일 단위로 분리한다. 랜덤 셔플 방식의 분리는 사용하지 않는다.

| 구분 | 기간 (8주 기준) |
|---|---|
| Training | 처음 5주 |
| Validation | 다음 1주 |
| Test | 마지막 2주 |

최종 평가는 **Walk-forward 검증**(1주 단위로 학습 기간을 늘려가며 다음 1주를 평가)으로 수행한다.

학기 중과 방학 기간의 교통 패턴이 다를 수 있으므로, 평가 기간에 방학이 포함되면 방학 여부별로 성능을 분리해 보고한다.

## 8.4 성공 기준

- **1차 목표**: walk-forward 평가에서 15분 후 속도 예측 MAE가 현재 속도 유지 모델보다 **10% 이상 낮을 것**
- **2차 목표**: 모든 horizon에서 세 기준 모델 중 가장 좋은 모델보다 MAE가 낮을 것
- 정체 시작 구간에서 기준 모델 대비 개선 여부를 별도로 보고한다.

수치 목표는 데이터 축적 후 기준 모델 성능을 확인한 시점에 재검토한다.

---

# 9. 프로그램 화면 설계

초기 대시보드는 Streamlit을 사용한다. 화면은 60초마다 자동 갱신한다.

## 9.1 메인 대시보드

표시 항목:

- 최신 데이터 기준 시각 및 수집 시각
- **데이터 상태**: 최신 데이터가 10분 이상 지연되면 경고 표시, 최근 수집 결과(success/partial/failed)
- 분석 대상 도로 및 구간 순서도
- 구간별 현재 평균 속도
- 구간별 혼잡 상태
- 예측 결과

## 9.2 혼잡 상태 등급

수집원이 소통 상태 코드를 제공하면 원본 코드를 표시한다. 제공하지 않으면 속도 기준 파생 등급을 사용하고 "파생값"임을 표시한다.

| 등급 | 속도 기준 (초기값) |
|---|---|
| 원활 | 40 km/h 이상 |
| 서행 | 20~40 km/h |
| 정체 | 20 km/h 미만 |

※ 기준값은 수집원 기준이 확인되면 그에 맞춘다.

## 9.3 도로 구간별 교통정보

| 구간 | 현재 속도 | 5분 후 | 10분 후 | 15분 후 | 30분 후 |
|---|---:|---:|---:|---:|---:|
| S1 | - | - | - | - | - |
| S2 | - | - | - | - | - |
| S3 | - | - | - | - | - |
| S4 | - | - | - | - | - |
| S5 | - | - | - | - | - |
| S6 | - | - | - | - | - |

실제 수집 및 예측 데이터가 없을 때는 임의의 수치를 표시하지 않고 '-'로 표시한다. `degraded` 예측은 별도 표시(예: 회색)하고, `skipped` 예측은 '-'로 표시한다.

## 9.4 시계열 그래프

- 시간대별 실제 평균 속도
- 시간대별 예측 평균 속도 (horizon 선택)
- 실제값·예측값·기준 모델 비교
- 구간별 속도 변화 (시간×구간 히트맵)
- 교통량 데이터 확보 시 교통량 그래프

## 9.5 모델 성능 화면

- 활성 모델 버전, 학습 기간
- horizon별·구간별 MAE, RMSE, WAPE와 기준 모델 대비 개선율
- 최근 1주 실시간(live) 예측 오차 추이

---

# 10. 내부 API 설계 (참고용, MVP 제외)

MVP에서는 별도 웹 서버를 구축하지 않고 Python 모듈과 SQLite를 직접 사용한다. 아래는 향후 FastAPI 전환 시 참고할 인터페이스다.

| Method | Endpoint | 설명 | 데이터원 |
|---|---|---|---|
| GET | /api/segments | 도로 구간 목록 | road_segment, segment_link |
| GET | /api/traffic/current | 현재 교통정보 | segment_traffic_5min |
| GET | /api/traffic/history | 과거 교통정보 | segment_traffic_5min |
| POST | /api/collector/run | 데이터 수집 실행 | - |
| POST | /api/model/train | 모델 학습 | - |
| POST | /api/prediction/run | 예측 실행 | - |
| GET | /api/prediction/latest | 최신 예측 결과 | traffic_prediction |
| GET | /api/model/evaluation | 모델 평가 결과 | model_evaluation |

---

# 11. 프로젝트 폴더 구조

```text
changwon_traffic_prediction/
│
├── .opencode/agents/         # 에이전트 역할·권한 정의 (AGENTS.md 2장)
├── docs/
│   ├── contracts/            # 모듈 간 인터페이스 계약 (C-01~C-06)
│   ├── research/             # 리서치 결과 (R-xx), samples/
│   └── tasks/BOARD.md        # 작업 현황판
│
├── common/                   # 공용 코드: KST 시간 헬퍼, 로깅 설정
│
├── config/
│   ├── settings.py           # 환경변수 로드, 경로, 임계값
│   └── segments.py           # 구간·링크 시드 데이터 (DB 초기 적재용)
│
├── collector/
│   ├── base_collector.py
│   ├── police_utic_collector.py
│   ├── its_collector.py
│   ├── weather_collector.py
│   └── scheduler.py          # APScheduler 상주 프로세스
│
├── database/
│   ├── db.py                 # 연결, WAL·FK 설정
│   ├── models.py             # SQLAlchemy 모델
│   ├── schema.sql            # 5장 DDL
│   └── repository.py
│
├── preprocessing/
│   ├── clean_data.py         # 이상치 판정
│   ├── aggregate_data.py     # 5분 구간 집계
│   └── make_features.py      # as-of 특성 생성
│
├── prediction/
│   ├── train.py
│   ├── predict.py
│   ├── evaluate.py
│   └── baseline.py
│
├── dashboard/
│   └── app.py                # 내부 대시보드 (Streamlit)
│
├── publisher/                # Phase 2: 공개 JSON 생성·업로드
│   ├── build_public.py
│   └── upload.py
│
├── web/                      # Phase 2: 시민 공개 정적 페이지
│   ├── index.html
│   ├── app.js
│   ├── style.css
│   ├── manifest.webmanifest
│   └── about.html            # 정확도 설명, 출처, 면책
│
├── scripts/
│   ├── init_db.py
│   ├── load_segments.py
│   └── backup_db.py
│
├── notebooks/                # 탐색적 분석
│
├── data/
│   ├── raw/                  # 원본 응답 (압축 보관)
│   ├── reference/            # 표준노드링크 SHP 등
│   └── processed/
│
├── saved_models/
├── logs/
├── tests/
│   ├── contracts/            # 계약 테스트 (오케스트레이터 소유)
│   ├── fixtures/             # 공용 합성 픽스처 (synthetic 표시, 테스트 전용)
│   ├── collector/  database/  preprocessing/
│   └── prediction/ dashboard/ publisher/
│
├── .env
├── .env.example
├── .gitignore                # .env, data/, logs/, saved_models/, *.db 제외
├── requirements.txt
├── AGENTS.md                 # Agentic 개발 원칙
├── PRD.md
├── SPEC.md
└── README.md
```

경로별 소유 에이전트와 수정 권한은 `AGENTS.md` 2장을 따른다.

---

# 12. 개발 환경 및 라이브러리

| 구분 | 기술 |
|---|---|
| Language | Python 3.11 이상 |
| HTTP 통신 | requests, tenacity(재시도) |
| XML 파싱 | lxml 또는 xmltodict |
| 스케줄링 | APScheduler |
| 데이터 처리 | pandas, numpy |
| 공간 데이터 | geopandas (표준노드링크 SHP 확인용, 개발 시에만) |
| DB | SQLite |
| ORM | SQLAlchemy 2.x |
| 머신러닝 | scikit-learn, xgboost |
| 모델 저장 | joblib (XGBoost는 `save_model` JSON 병행) |
| 시각화 | Streamlit, Plotly |
| 달력 | holidays |
| 환경변수 | python-dotenv |
| 로깅 | logging (일 단위 로테이션, 30일 보관) |
| 테스트 | pytest |

`requirements.txt`에는 버전을 고정한다. API 인증키는 `.env` 파일로 관리하며 Git 등에 업로드하지 않는다.

---

# 13. 비기능 요구사항

## 13.1 안정성

- API 오류가 발생해도 수집 프로세스가 종료되지 않아야 한다.
- 수집 실패 이력을 기록해야 한다.
- 중복 데이터 저장을 DB 제약으로 방지해야 한다.
- 모델 학습과 데이터 수집 작업을 분리해야 한다.
- PC 재부팅 후 수집이 자동으로 재개되어야 한다.

## 13.2 성능

- 수집 완료부터 예측 저장까지 30초 이내에 처리한다.
- 대시보드 첫 화면은 3초 이내에 표시한다.

## 13.3 데이터 신뢰성

- 원본 데이터와 전처리 데이터를 별도 테이블로 구분한다.
- 원본 관측 시각과 수집 시각을 모두 보존한다.
- 결측값과 실제 0을 구분한다.
- 학습 데이터에 미래 정보가 포함되지 않도록 6.6의 규칙을 따른다.
- 데이터 제공처와 데이터 갱신 시각을 기록한다.
- 원본 응답을 보관해 재처리할 수 있어야 한다.

## 13.4 보안

- API 인증키 외부 노출 금지
- `.env` 파일 Git 제외 (`.gitignore`)
- 불필요한 개인정보 수집 금지 (향후 CCTV 활용 시 차량 번호판 등 개인정보 비식별 처리 원칙 별도 수립)
- Phase 2: 공개 서비스 보안 요구사항은 20.7을 따른다.

## 13.5 확장성

향후 다음 기능을 추가할 수 있도록 설계한다.

- 창원시 다른 주요 도로 추가
- 양방향 교통 흐름 예측
- CCTV 기반 차량 검출
- 교통사고 및 공사 정보 반영
- FastAPI 기반 서버 전환
- PostgreSQL 기반 데이터 저장
- 시민 공개 화면의 지도 표시, 알림 구독
- 수집·예측의 서버 이전 (발행 JSON 형식을 유지해 공개 페이지 수정 없이 전환)

---

# 14. 테스트 및 완료 기준

## 14.1 데이터 수집 테스트

| ID | 항목 | 관련 FR |
|---|---|---|
| T-COL-01 | API 정상 응답 및 인증(키·IP) 확인 | FR-001 |
| T-COL-02 | XML 응답 파싱 (정상·빈 응답·오류 응답 샘플) | FR-001 |
| T-COL-03 | 타임아웃·재시도·인증 오류 처리 | FR-001 |
| T-COL-04 | 창원대로 대상 링크 전체 식별 | FR-002 |
| T-COL-05 | 진행 방향 구분 (링크 시작·종료 노드) | FR-002 |
| T-COL-06 | 부분 응답 시 partial 기록 | FR-002 |
| T-COL-07 | 수집 데이터 DB 저장 및 원본 파일 보관 | FR-003 |
| T-COL-08 | 데이터 갱신 주기 확인 (원본 시각 간격 분포) | - |

## 14.2 데이터 처리 테스트

| ID | 항목 | 관련 FR |
|---|---|---|
| T-PRC-01 | 중복 저장 방지 | FR-003 |
| T-PRC-02 | 이상치 유형별 플래그 부여 | FR-004 |
| T-PRC-03 | 결측이 0으로 변환되지 않음 | FR-004 |
| T-PRC-04 | 짧은 결측 forward fill, 장시간 결측 유지 | FR-004 |
| T-PRC-05 | 갱신 정지(frozen) 판정 | FR-004 |
| T-PRC-06 | 5분 bin 할당 및 KST 정규화 | FR-005 |
| T-PRC-07 | 거리 가중 조화평균 계산 (수기 계산값과 비교) | FR-005 |
| T-PRC-08 | 부분 관측 70% 기준 적용 | FR-005 |
| T-PRC-09 | as-of 조인 시 미래 데이터 미포함 검증 | FR-006 |

## 14.3 예측 테스트

| ID | 항목 | 관련 FR |
|---|---|---|
| T-PRD-01 | horizon별 모델 학습 및 registry 등록 | FR-006 |
| T-PRD-02 | 5, 10, 15, 30분 후 예측 저장 | FR-007 |
| T-PRD-03 | 입력 결측 시 degraded/skipped 처리 | FR-007 |
| T-PRD-04 | 대상 시각 도래 후 실제값·오차 갱신 | FR-008 |
| T-PRD-05 | 기준 모델 3종 예측 및 비교 | FR-009 |
| T-PRD-06 | walk-forward 평가 결과 저장 | FR-009 |

## 14.4 대시보드 테스트

| ID | 항목 | 관련 FR |
|---|---|---|
| T-DSH-01 | 데이터 없을 때 '-' 표시 | FR-010 |
| T-DSH-02 | 10분 이상 지연 시 경고 표시 | FR-010 |
| T-DSH-03 | 실제값·예측값 비교 그래프 | FR-010 |

## 14.5 시민 공개 테스트 (Phase 2)

| ID | 항목 | 관련 FR |
|---|---|---|
| T-PUB-01 | 모바일 화면(360px 폭)에서 구간 목록·탭·기준 시각 표시 | FR-013 |
| T-PUB-02 | 10분 지연 시 예측 숨김·배너, 30분 지연 시 현재 상태 숨김 | FR-013 |
| T-PUB-03 | 운영 시간 외·공휴일 안내 문구 | FR-013 |
| T-PUB-04 | 구간 예측 보류 시 "정보 없음" 표시 | FR-013 |
| T-PUB-05 | 색 없이(흑백) 등급 구분 가능, 글자 200% 확대 시 레이아웃 유지 | FR-013 |
| T-PUB-06 | 4G 환경 2초 이내 표시, 전송량 200KB 이하 | FR-013 |
| T-PUB-07 | 공개 JSON 스키마 검증 (내부 필드·품질 플래그 미포함) | FR-014 |
| T-PUB-08 | 예측 저장 후 1분 이내 발행 | FR-014 |
| T-PUB-09 | 업로드 실패 시 재시도·`publish_log` 기록·내부 대시보드 경고 | FR-014 |
| T-PUB-10 | 점검 모드 전환 시 1분 이내 반영 | FR-014 |

## 14.6 MVP 완료 조건

1. 창원대로 분석 대상 링크를 식별하고 `segment_link`에 등록했다.
2. 실제 교통정보를 자동으로 수집·저장하며, 최근 2주간 평일 06:00~10:00 수집 성공률(success+partial)이 95% 이상이다.
3. 모든 예측 대상 구간의 5분 시계열이 생성된다.
4. 평균 속도 예측이 매 5분 자동 실행되고 결과를 대시보드에서 확인할 수 있다.
5. 실제값과 예측값을 비교할 수 있다.
6. 기준 모델 대비 성능 평가 결과(8.4)를 확인할 수 있다.
7. 데이터 수집 실패 및 오류를 `collection_log`와 로그 파일로 추적할 수 있다.

예측 정확도 목표(8.4)는 데이터 축적 후 기준 모델 성능을 확인한 시점에 재검토한다.

---

# 15. 개발 일정

데이터 축적에 가장 오랜 시간이 걸리므로, **수집기를 가장 먼저 가동하고 나머지 개발은 축적과 병행**한다.

| 단계 | 개발 내용 | 예상 기간 | 비고 |
|---|---|---|---|
| 1단계 | 교통정보 API 조사·활용 신청·검증 | 3~5일 | 승인 대기 포함 |
| 2단계 | 표준노드링크 기반 링크·구간 매핑 | 2~3일 | 1단계와 병행 |
| 3단계 | 최소 수집기 개발 및 **상시 수집 시작** | 3~5일 | 원본 저장 우선 |
| 4단계 | DB 스키마·전처리 개발 | 3~4일 | 수집과 병행 |
| 5단계 | 2주 시점 파이프라인 시험 | 2일 | 결측·이상치 기준 점검 |
| 6단계 | 기준 모델·XGBoost 모델 개발 | 4~7일 | 축적 데이터로 반복 |
| 7단계 | 대시보드 개발 | 3~5일 | |
| 8단계 | 8주 이상 축적 후 정식 평가 | 수집 시작 후 8~12주 | |
| 9단계 | 성능 검증 및 개선 | 지속 진행 | |
| 10단계 | 공개 페이지·발행 모듈 개발, 운영 단계 API 승인 신청 | 5~7일 | 8단계와 병행 |
| 11단계 | 연속 4주 실시간 성능 확인 → 비공개 시범(2주) → 시민 공개 | 6주 이상 | 공개 조건(PRD 8.2) 충족 시 |

※ API 승인, 데이터 확보 기간 및 데이터 품질에 따라 일정이 변경될 수 있다.
※ 2026년 11월 수집 시작 시 12월 말부터 겨울방학 기간이 포함되므로 평가 시 8.3의 방학 분리 보고를 적용한다.

---

# 16. 주요 위험요소 및 대응 방안

| 위험요소 | 영향 | 대응 방안 |
|---|---|---|
| 창원대로 API 데이터 미제공 | 모델 개발 불가 | 경찰청(UTIC), ITS, UTIS 순으로 대체 경로 확인 |
| 교통량 데이터 미제공 | 교통량 예측 불가 | 속도 예측 우선, CCTV 검토 |
| 링크 ID 매핑 실패 | 구간별 분석 오류 | 표준노드링크 SHP와 지도로 링크 속성·방향 검증 |
| 표준노드링크 버전 변경 | 링크 ID 불일치 | `nodelink_ver`·`valid_from/to`로 매핑 이력 관리 |
| 지하차도 본선·측도 혼동 | 구간 속도 왜곡 | `is_mainline` 구분, 본선 기준 산출 |
| 데이터 갱신 간격 불규칙 | 학습 품질 저하 | 5분 bin 정규화, available_at 기록 |
| 수집 기간 부족 | 모델 일반화 성능 저하 | 상시 수집, 최소 8주 축적 후 평가 |
| 계절·방학 패턴 변화 | 평가 기간 분포 차이 | 방학 특성 추가, 방학 여부별 성능 보고 |
| 교통량 집계 범위 불일치 | 예측값 왜곡 | 원본 집계 기준 확인, 링크 간 합산 금지 |
| 로컬 PC 중단(절전·재부팅·업데이트) | 수집 공백 | 자동 시작 등록, 절전 해제, 업데이트 시간 조정, 공백 모니터링 |
| IP 인증 실패(유동 IP 변경) | 수집 중단 | 고정 IP 확인 또는 IP 변경 시 재등록 절차 마련, auth_error 경고 |
| 시스템 시각 오차 | 시각 정합성 오류 | NTP 동기화 |
| 이용약관 위반(웹 스크레이핑) | 법적·접근 차단 위험 | 공식 API만 사용 |
| (Phase 2) 오예측 공개 | 시민 판단 오류, 신뢰 하락 | 공개 조건, 정확도 표시, 면책 문구, 적중률 하락 시 예측 표시 자동·수동 중단 |
| (Phase 2) 오래된 정보 노출 | 잘못된 출발 판단 | `generated_at` 기준 클라이언트 측 자동 숨김(20.5) |
| (Phase 2) 발행 인증정보 유출 | 공개 페이지 변조 | 업로드 전용 최소 권한 키, `.env` 관리, 정기 교체 |
| (Phase 2) 공공데이터 이용 조건 | 서비스 중단 | 운영 단계 승인, 출처 표기, 원본 재배포 금지 |
| (Phase 2) 공식 서비스 오인 | 민원·책임 문제 | 비공식 서비스임을 화면에 명시 |

---

# 17. 최종 개발 추진 전략

**Phase 1. 데이터 확보 검증**

- 경찰청 교통소통정보(UTIC)·ITS·UTIS API 확인 및 활용 신청
- API 인증(키·IP) 및 호출 테스트
- 표준노드링크로 창원대로 링크 ID·길이·방향 확인
- 평균 속도·통행시간·교통량 필드 및 결측 표현 확인

**Phase 2. 데이터 수집 시스템**

- 최소 수집기 개발 및 상시 수집 시작
- SQLite 스키마 구축
- 이상치·결측 처리 및 5분 구간 집계
- 수집 로그 및 오류 관리

**Phase 3. 교통 예측 모델**

- as-of 특성 생성
- 기준 모델 3종 구현
- XGBoost 학습 및 하이퍼파라미터 탐색
- 5~30분 후 속도 예측 파이프라인 자동화
- walk-forward 기준 모델 대비 성능 검증

**Phase 4. 대시보드 및 검증**

- 구간별 현재 교통 상태 및 데이터 상태 표시
- 미래 교통 흐름 표시
- 실제값과 예측값 비교
- 예측 성능 분석

---

# 18. 현재 미확정 사항

| 항목 | 현재 상태 |
|---|---|
| 경찰청 교통소통정보(UTIC)의 창원대로 제공 여부 | 검증 필요 |
| ITS 소통정보의 창원대로 제공 여부 | 검증 필요 |
| UTIS 공식 Open API 제공 여부 | 검증 필요 |
| 실제 링크 ID 및 표준노드링크 버전 | 미확정 |
| 분석 구간의 정확한 경계 및 링크 길이 | 미확정 (3.3 후보 기준) |
| 지하차도 본선·측도 링크 분리 여부 | 검증 필요 |
| 평균 속도 제공 여부 및 단위 | 검증 필요 |
| 속도 0·결측 표현 방식 | 검증 필요 |
| 교통량 제공 여부 및 단위 | 검증 필요 |
| API 갱신 주기 | 검증 필요 |
| API 호출 제한 (상시 수집 가능 여부) | 검증 필요 |
| 수집 PC의 IP 고정 여부 | 확인 필요 |
| 링크별 제한속도 | 확인 필요 |
| CCTV 차량 검출 적용 여부 | 후속 결정 |
| (Phase 2) 운영 단계 API 승인 및 출처 표기 요건 | 확인 필요 |
| (Phase 2) 공개 페이지 호스팅 서비스·도메인 | 미결정 |
| (Phase 2) 운영 주체 표기 및 문의 수단 | 미결정 |
| (Phase 2) 공개 화면의 속도 수치 노출 여부 | 미결정 |

**중요:** 본 문서는 v1.2 초안이다. 실제 API 데이터 스키마와 도로 링크 매핑이 확인되면 데이터 수집 명세, 구간 정의, 이상치 기준을 v1.3으로 갱신한다.

---

# 19. 최종 프로젝트 정의

창원시 창원대로의 팔용동에서 성산구·산업단지 방향(팔용사거리~성주광장)으로 이동하는 평일 아침 출근 차량의 교통 흐름을 분석하고, 실시간 및 과거 교통정보를 활용해 도로 구간별 5~30분 후 평균 속도를 예측하는 Python 기반 머신러닝 시스템을 구축한다.

초기에는 6개 도로 구간(S1~S6)의 평균 속도 예측을 핵심 기능으로 구현하며, 실제 교통량 데이터가 확보되면 교통량 예측 기능을 확장한다. 기준 모델 대비 성능이 검증되면 예측 결과를 일반 시민이 볼 수 있는 모바일 웹으로 공개한다(Phase 2).

**개발의 최우선 과제는 모델 구현이 아니라 실제 창원대로 교통 데이터 확보 및 검증이며, 이를 위해 수집기를 가장 먼저 가동한다.**

---

# 20. 시민 공개 서비스 (Phase 2)

제품 요구사항과 공개 조건은 `PRD.md` 5.6, 8.2를 따른다. 이 장은 구현 명세를 정의한다.

## 20.1 설계 원칙

1. **검증된 예측만 공개한다.** 공개 조건(PRD 8.2) 충족 전에는 공개 URL을 배포하지 않는다.
2. **로컬 PC로 들어오는 외부 요청은 없다.** 로컬 PC는 결과 파일을 외부 정적 호스팅으로 업로드(outbound)만 한다.
3. **잘못된 정보를 보여주느니 보여주지 않는다.** 데이터 신선도 판단은 브라우저에서도 수행해, PC가 꺼져 발행이 멈춰도 오래된 예측이 표시되지 않게 한다.
4. **가공 결과만 공개한다.** 원본 API 응답, 링크 단위 원본 값, 내부 품질 플래그는 공개하지 않는다.

## 20.2 구성

```
[로컬 PC]                                         [외부 정적 호스팅 (HTTPS, CDN)]
 수집 → 전처리 → 예측 → DB                          ├─ index.html / app.js / style.css
                    │                               ├─ about.html
                    └─ publisher/build_public.py    └─ data/latest.json   ← 5분마다 덮어쓰기
                          → publisher/upload.py ───────▶  (Cache-Control: max-age=30)
                                                     ▲
                                        [시민 브라우저] 60초마다 latest.json 조회
```

- 호스팅은 정적 파일 + HTTPS + 업로드용 API/CLI를 지원하는 서비스(객체 스토리지+CDN 또는 정적 사이트 호스팅)를 사용한다. 구체적 서비스는 미결(18장)이다.
- 정적 자원(html/js/css)은 배포 시에만 업로드하고, 운영 중에는 `latest.json`만 갱신한다.
- 업로드 인증정보는 해당 버킷·사이트의 쓰기 권한만 가진 최소 권한 키를 사용하고 `.env`로 관리한다.

## 20.3 공개 JSON 스키마 (`data/latest.json`)

```json
{
  "schema_version": 1,
  "generated_at": "2027-02-15T07:35:20+09:00",
  "base_time": "2027-02-15T07:35:00+09:00",
  "status": "ok",
  "service_hours": { "days": "weekday_non_holiday", "start": "06:30", "end": "09:30" },
  "is_service_time": true,
  "direction_label": "팔용동 → 성산구·산업단지 방면",
  "segments": [
    {
      "order": 1,
      "name": "팔용사거리 → 평산사거리",
      "now":  { "grade": "free",   "speed_kmh": 52 },
      "h15":  { "grade": "free",   "speed_kmh": 47 },
      "h30":  { "grade": "slow",   "speed_kmh": 33 }
    },
    {
      "order": 4,
      "name": "용원교차로 → 교육단지사거리",
      "now":  { "grade": "slow",   "speed_kmh": 34 },
      "h15":  { "grade": "jam",    "speed_kmh": 18 },
      "h30":  null
    }
  ],
  "accuracy": {
    "period_days": 5,
    "h15_grade_accuracy": 0.81,
    "h30_grade_accuracy": 0.74
  },
  "notice": null
}
```

| 필드 | 규칙 |
|---|---|
| `status` | `ok` / `degraded`(일부 구간 정보 없음) / `stale`(발행 시점에 이미 데이터 지연) / `maintenance`(점검 모드) |
| `grade` | `free`(원활) / `slow`(서행) / `jam`(정체). 9.2 기준과 동일 |
| `speed_kmh` | 정수로 반올림. 공개 여부는 미결(18장)이며, 비공개로 결정되면 필드를 제외한다 |
| `now` / `h15` / `h30` | 값이 없거나 `input_quality`가 `skipped`·`degraded`이면 `null` |
| `accuracy` | 최근 평일 5일(운영 시간 내) `model_evaluation`의 live 등급 적중률. 표본이 부족하면 `null` |
| `notice` | 운영자 공지 문구(선택) |

- 구간 ID(S1 등), 모델 버전, 품질 플래그, 원본 값은 포함하지 않는다.
- 파일 크기는 10KB 이하를 목표로 한다.
- S0(상류 참고 구간)는 포함하지 않는다.

## 20.4 화면 명세

| 영역 | 명세 |
|---|---|
| 상단 | 서비스명, `direction_label`, "HH:MM 기준"(`base_time`) |
| 탭 | `지금` / `15분 후` / `30분 후`. 기본 `지금`. 선택 상태는 URL 해시로 유지 |
| 구간 목록 | `order` 순 세로 나열. 각 행: 구간 이름, 등급 배지(색 + "원활/서행/정체" 글자), 보조로 속도 |
| 정확도 | "최근 평일 5일 15분 후 예측 적중률 81%" (탭에 맞는 horizon 값 표시), `about.html` 링크 |
| 하단 | 데이터 출처(예: "교통정보 출처: 경찰청 도시교통정보센터, 공공데이터포털"), 면책 문구, "운전 중에는 이용하지 마세요", 비공식 서비스 안내, 문의 수단 |

- 기술: 프레임워크 없는 HTML/CSS/JavaScript. 외부 스크립트·폰트 CDN을 쓰지 않는다.
- 모바일 우선(최소 360px 폭), 다크 모드 대응(`prefers-color-scheme`).
- 등급 색은 색각 이상자도 구분 가능한 조합을 쓰고, 항상 글자를 함께 표시한다.
- `manifest.webmanifest`로 홈 화면 추가를 지원한다. 서비스 워커로 데이터를 캐시하지 않는다(오래된 정보 노출 방지).
- 검색 노출: 비공개 시범(M6) 동안 `noindex`, 공개(M7) 시 해제한다.

**면책 문구(초안, 확정 전 검토 필요)**
> 이 서비스는 공공 교통정보를 바탕으로 한 비공식 예측이며, 실제 교통 상황과 다를 수 있습니다. 교통 상황 판단과 운전에 대한 책임은 이용자에게 있습니다.

## 20.5 표시 규칙 (브라우저에서 판단)

브라우저는 `latest.json`을 60초마다 조회하고, **현재 시각과 `generated_at`의 차이**로 신선도를 판단한다. 조회 자체가 실패하면 직전 데이터로 같은 규칙을 적용한다.

| 조건 | 화면 동작 |
|---|---|
| `status = maintenance` | "서비스 점검 중" + `notice`만 표시 |
| 지연 30분 이상 | 구간 정보 전부 숨김, "현재 교통정보를 불러올 수 없습니다" 안내 |
| 지연 10분 이상 30분 미만 | "업데이트 지연" 배너, 예측 탭 비활성화, `지금` 값은 "HH:MM 기준"과 함께 흐리게 표시 |
| `is_service_time = false` | 예측 탭 비활성화, "예측은 평일 06:30~09:30에만 제공됩니다" 안내, `지금` 값은 정상 표시 |
| 구간 값이 `null` | 해당 칸 "정보 없음" |
| `accuracy`가 `null` | 정확도 영역에 "정확도 집계 중" 표시 |

브라우저 시계가 크게 틀린 경우를 대비해, 응답 헤더 `Date`와 브라우저 시각의 차이가 5분 이상이면 `Date` 헤더 기준으로 계산한다.

## 20.6 발행 및 운영

**발행 절차** (7.6 파이프라인의 5단계로 추가)

```
  5. build_public.py: DB → latest.json 생성 (스키마 검증 통과 시에만)
  6. upload.py: 임시 이름으로 업로드 후 교체(가능한 경우) → publish_log 기록
```

- 운영 시간 외에도 `지금` 값과 `is_service_time=false`로 5분마다 발행한다.
- 업로드 실패 시 30초 간격 최대 3회 재시도, 실패하면 내부 대시보드에 경고를 표시한다.
- **점검 모드**: `config`의 플래그(또는 `scripts/maintenance.py on|off`)로 전환하며, 전환 즉시 `status=maintenance`로 발행한다.
- **자동 예측 중단**: 최근 평일 5일 15분 후 등급 적중률이 공개 조건 시점 값보다 5%p 이상 낮아지면 예측(`h15`, `h30`)을 `null`로 발행하고 개발자에게 경고한다. 해제는 수동으로 한다.

```sql
CREATE TABLE publish_log (
    id            INTEGER PRIMARY KEY,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    base_time     TEXT,
    status        TEXT NOT NULL,      -- success / failed / skipped_validation
    public_status TEXT,               -- ok / degraded / stale / maintenance
    bytes         INTEGER,
    error_message TEXT
);
```

**이용 통계**: 호스팅 서비스의 요청 로그 집계 또는 쿠키를 쓰지 않는 집계 방식만 사용한다. 개인을 식별할 수 있는 정보(IP 원문 등)는 저장하지 않는다. 통계 도구를 도입하면 개인정보 처리방침 필요 여부를 확인한다.

## 20.7 보안·법적 요구사항

- 로컬 PC에 포트 개방, 원격 접속 경로를 만들지 않는다.
- 업로드 키는 쓰기 전용 최소 권한으로 발급하고 6개월마다 교체한다.
- 공개 페이지는 HTTPS로만 제공하고, CSP(`default-src 'self'`) 헤더를 적용한다.
- 공공데이터포털 **운영 단계 활용 승인**을 받은 후 공개한다. 출처 표기는 제공기관 요건을 따른다.
- 원본 API 응답을 그대로 재배포하지 않는다.
- 면책 문구는 공개 전 최종 확정하고, 필요하면 법률 검토를 받는다(PRD Q10).
