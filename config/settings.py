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
    grade_slow_min_kmh: float = 20.0

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
