"""혼잡 등급 (SPEC 9.2). 대시보드, 평가(등급 적중률), 공개 JSON이 모두 이 함수를 쓴다."""

from __future__ import annotations

import math
from typing import Literal

from config.settings import Settings

Grade = Literal["free", "slow", "jam"]

GRADE_LABEL: dict[str, str] = {"free": "원활", "slow": "서행", "jam": "정체"}


def grade(speed: float | None, s: Settings) -> Grade | None:
    """속도(km/h) → 등급. 값이 없거나 NaN이면 None(결측을 등급으로 만들지 않는다)."""
    if speed is None or math.isnan(speed):
        return None
    if speed >= s.grade_free_min_kmh:
        return "free"
    if speed >= s.grade_slow_min_kmh:
        return "slow"
    return "jam"
