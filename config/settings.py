"""설정값. 코드에 임계값·경로·URL을 하드코딩하지 않고 여기서 읽는다.

비밀값(API 키)은 `.env`에서만 읽고 repr·로그에 노출하지 않는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _load_dotenv() -> None:
    from dotenv import load_dotenv

    load_dotenv(override=False)


@dataclass(frozen=True)
class Settings:
    db_path: str = "data/traffic.db"
    raw_dir: str = "data/raw"
    log_dir: str = "logs"

    # ITS 국가교통정보센터 교통소통정보 (R-02)
    its_api_key: str | None = field(default=None, repr=False)
    its_api_url: str = "https://openapi.its.go.kr:9443/trafficInfo"
    # (minX, maxX, minY, maxY) 경위도. TODO(R-02/R-03b): 추정치. 창원대로 링크 좌표로 좁힌다.
    its_bbox: tuple[float, float, float, float] = (128.55, 128.80, 35.15, 35.30)
    # DB에 저장할 도로(ITS roadName). 원본 파일은 응답 전체를 보관한다 (C-02 v2).
    its_store_road_names: tuple[str, ...] = ("창원대로",)

    police_utic_api_key: str | None = field(default=None, repr=False)

    http_timeout_s: float = 10.0
    http_retries: int = 3
    http_backoff_min_s: float = 1.0
    http_backoff_max_s: float = 30.0

    db_busy_timeout_ms: int = 5000

    # v0 상식선 상한. SPEC 6.4의 "제한속도 x 1.5"는 링크 제한속도 확보 후 Slice 1에서 적용한다.
    max_valid_speed_kmh: float = 150.0

    stale_minutes: int = 10
    horizons: tuple[int, ...] = (5, 10, 15, 30)

    # 혼잡 등급 경계 (SPEC 9.2). 내부 대시보드와 공개 화면이 같은 값을 쓴다.
    grade_free_min_kmh: float = 40.0
    # 대시보드 그래프·히트맵 색 축 상한(표시 전용). 실측 출근 속도가 대부분 80 미만이라 등급 색이 구분되게 둔다
    chart_max_kmh: float = 80.0
    grade_slow_min_kmh: float = 20.0

    # --- 전처리 (SPEC 6.2~6.4, Slice 1) ---
    partial_min_coverage: float = 0.7  # 본선 길이 기준 관측 비율 하한
    ffill_max_bins: int = 2  # 직전 값으로 채울 수 있는 연속 결측 bin 수
    frozen_repeat_count: int = 6  # 원본 시각이 바뀌는 동안 같은 값이 이만큼 이어지면 갱신 정지

    # --- 기준 모델·평가 (SPEC 8장, C-04) ---
    recent_mean_minutes: int = 15
    dow_mean_min_weeks: int = 3
    backfill_lookback_hours: int = 6
    eval_window: tuple[str, str] = ("07:00", "09:00")  # 대상 시각 기준, 양끝 포함
    congestion_onset_drop: float = 0.3

    # --- 달력 (R-05) ---
    temp_holidays: tuple[str, ...] = ()  # 임시공휴일 YYYY-MM-DD (holidays 패키지 반영 전 보정)
    # TODO(R-05): 2026은 언론 보도로 추정한 집단휴가 핵심 기간. 2027은 확인되면 추가한다.
    industrial_vacations: tuple[tuple[str, str], ...] = (("2026-08-03", "2026-08-07"),)
    school_vacations: tuple[tuple[str, str], ...] = ()

    # --- 운영 (Slice 1.5) ---
    eval_cron_hour: int = 10  # 일일 평가 실행 시각 (출근 시간대가 끝난 뒤)
    eval_cron_minute: int = 5
    backup_dir: str = "data/backup"
    backup_keep_days: int = 14  # SPEC 5.1
    backup_cron_hour: int = 3  # 일일 DB 백업 시각
    raw_keep_days: int = 30  # 원본 응답 파일 보관 기간 (하루 약 30MB)
    # 수집 성공률 (BOARD 정의): 평일·비공휴일 이 시간대의 5분 bin × 예측 대상 구간 중 실제 값이 있는 비율
    rate_window: tuple[str, str] = ("06:00", "10:00")  # bin_time 기준, 시작 포함·끝 제외
    rate_target: float = 0.95
    dow_mean_lookback_weeks: int = 8  # C-04 v1.3: dow_mean 조회 하한 (base_time − N주)
    rate_streak_days: int = 3  # Slice 0 완료 = 연속 service day 이만큼 rate_target 이상

    collect_cron_minute: str = "*/5"
    # 예정 시각에서 이만큼 늦어도 그 회차를 실행한다. 절전 등으로 더 늦으면 건너뛰고 다음 회차부터 실행한다.
    scheduler_misfire_grace_s: int = 60


def get_settings() -> Settings:
    """환경변수(.env 포함)를 반영한 설정을 돌려준다."""
    _load_dotenv()
    return Settings(
        db_path=os.environ.get("DB_PATH") or Settings.db_path,
        its_api_key=os.environ.get("ITS_API_KEY") or None,
        police_utic_api_key=os.environ.get("POLICE_UTIC_API_KEY") or None,
    )
