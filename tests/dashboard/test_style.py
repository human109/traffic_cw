"""dashboard.style 상태→글씨색 매핑 테스트."""

from __future__ import annotations

import pandas as pd

from dashboard.data import DASH
from dashboard.style import STATUS_BADGE, STATUS_TEXT_COLORS, status_badge_css, status_text_color

# Streamlit 기본 라이트/다크 배경(테마가 바뀌어도 대비 기준으로 쓴다).
LIGHT_BG = "#f0f2f6"
DARK_BG = "#0e1117"


def _relative_luminance(hexc: str) -> float:
    """WCAG 색상 대비 계산에 쓰는 상대 luminance."""
    hexc = hexc.lstrip("#")
    r, g, b = (int(hexc[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def linearize(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)


def _contrast(a: str, b: str) -> float:
    """두 색상 hex 사이의 WCAG 대비비(1.0 ~ 21.0)."""
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _style_block(html: str) -> str:
    start = html.index("<style")
    end = html.index("</style>")
    return html[start:end]


def test_status_text_color_grade_values() -> None:
    """원활/서행/정체는 각자의 색, 데이터 없음(-)은 회색을 반환한다."""
    assert status_text_color("원활") == f"color: {STATUS_TEXT_COLORS['원활']};"
    assert status_text_color("서행") == f"color: {STATUS_TEXT_COLORS['서행']};"
    assert status_text_color("정체") == f"color: {STATUS_TEXT_COLORS['정체']};"
    assert status_text_color(DASH) == f"color: {STATUS_TEXT_COLORS[DASH]};"


def test_status_text_color_unknown_value_is_gray() -> None:
    """매핑에 없는 값은 데이터 없음과 같은 회색으로 처리한다."""
    assert status_text_color("알 수 없는 상태") == f"color: {STATUS_TEXT_COLORS[DASH]};"


def test_status_text_colors_are_distinct_per_grade() -> None:
    """등급별 색은 서로 구분되어야 한다(색만으로는 안 되지만 색이 같으면 안 된다)."""
    colors = {STATUS_TEXT_COLORS[g] for g in ("원활", "서행", "정체")}
    assert len(colors) == 3
    assert len({status_text_color(g) for g in ("원활", "서행", "정체")}) == 3


def test_status_text_colors_readable_on_light_and_dark_background() -> None:
    """밝은/어두운 배경 모두에서 글씨로 읽히는 대비(≥ 3:1)를 가져야 한다."""
    for color in STATUS_TEXT_COLORS.values():
        assert _contrast(color, LIGHT_BG) >= 3.0, color
        assert _contrast(color, DARK_BG) >= 3.0, color


def test_status_styler_map_styles_only_status_column() -> None:
    """`df.style.map(status_text_color, subset=["상태"])`가 상태 열에만 색을 입힌다."""
    df = pd.DataFrame(
        [
            {"현재 속도": "45", "상태": "원활"},
            {"현재 속도": "10", "상태": "-"},
        ]
    )
    html = df.style.map(status_text_color, subset=["상태"]).to_html()
    block = _style_block(html)
    # 상태는 마지막 컬럼(col1)이므로 속도(col0)에 귀속된 셀에는 규칙이 없다.
    assert "_col0" not in block
    assert "_row0_col1 {" in block and "_row1_col1 {" in block
    assert "color: #1e7d32;" in block
    assert "color: #6e6e6e;" in block


def test_status_badge_contrast_wcag_aa() -> None:
    """상태 배지(bg/fg)는 WCAG AA 대비(≥ 4.5:1)를 만족해야 한다."""
    for status, colors in STATUS_BADGE.items():
        assert "bg" in colors and "fg" in colors
        assert _contrast(colors["bg"], colors["fg"]) >= 4.5, f"배지 대비 불량: {status}"
