"""상태(혼잡 등급) → 상태 글씨색 매핑(순수 함수). 근거: SPEC 9.2, 9.3, 20.4.

- `dashboard.data.grade`가 만든 상태 문자열("원활"/"서행"/"정체"/"-")을 화면용 글씨색으로 바꾼다.
- 데이터 조회·가공 로직이 아니라 스타일 전용 순수 함수다. DB를 쓰지 않고 인자 하나만 받는다.
- 색은 항상 글자와 함께 쓰여 색각 이상자도 등급을 알 수 있다(SPEC 20.4).
- 값이 없으면 "-"를 쓰고 회색으로 표시한다.
"""

from __future__ import annotations

from dashboard.data import DASH

# 상태 → 글씨색(hex). UI 상수이므로 dashboard/ 안에 둔다(config/ 소유는 아니다).
# 밝은 배경(예: #f0f2f6)과 어두운 배경(예: #0e1117) 양쪽에서 대비가 살아나도록
# 중간 명도의 계열색을 사용한다(각색 WCAG 대비비 ≥ 3:1).
STATUS_TEXT_COLORS: dict[str, str] = {
    "원활": "#1e7d32",  # 초록 계열
    "서행": "#b45309",  # 주황/앰버 계열
    "정체": "#c62828",  # 빨강 계열
    DASH: "#6e6e6e",  # 데이터 없음(혼잡 아님) → 회색
}

UNKNOWN_STATUS_COLOR = "#6e6e6e"


def status_text_color(value: str) -> str:
    """상태 문자열 → 표에 쓰는 글씨색.

    pandas Styler의 `map`은 셀 스타일을 CSS 선언 문자열로 받는다(`color: #xxxxxx;`).
    그래서 이 함수는 Styler에 그대로 넘길 수 있는 CSS 색상 선언을 반환한다.
    """
    hex_color = STATUS_TEXT_COLORS.get(value, UNKNOWN_STATUS_COLOR)
    return f"color: {hex_color};"
