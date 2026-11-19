"""판정 함수 단위 테스트 (D-DAT-02b). DB를 모르는 순수 함수라 `fixture_conn`이 필요 없다."""

from __future__ import annotations

import pytest

from preprocessing import rules


def test_frozen_mask_needs_repeat_count() -> None:
    # 5회 연속은 갱신 정지가 아니다. 6번째(=repeat_count번째) 관측부터 뺀다.
    assert rules.frozen_mask([30.0] * 5, 6) == [False] * 5
    assert rules.frozen_mask([30.0] * 6, 6) == [False] * 5 + [True]
    assert rules.frozen_mask([30.0] * 8, 6) == [False] * 5 + [True] * 3


def test_frozen_mask_counts_consecutive_only() -> None:
    # 값이 바뀌면 연속이 끊긴다: 30이 3회 연속인 구간만 표시된다.
    assert rules.frozen_mask([30.0, 30.0, 30.0, 31.0, 30.0, 30.0], 3) == [
        False, False, True, False, False, False,
    ]
    assert rules.frozen_mask([30.0, 31.0, 30.0, 31.0, 30.0, 31.0], 3) == [False] * 6


def test_frozen_mask_empty() -> None:
    assert rules.frozen_mask([], 6) == []


def test_coverage_by_length() -> None:
    assert rules.coverage([500.0, 700.0], [500.0]) == pytest.approx(500 / 1200)
    assert rules.coverage([500.0, 700.0], [500.0, 700.0]) == pytest.approx(1.0)


def test_coverage_falls_back_to_link_count_when_length_unknown() -> None:
    # 길이를 모르는 링크가 있으면 링크 수 비율로 대신한다(Slice 0 규칙).
    assert rules.coverage([800.0, None], [None]) == pytest.approx(0.5)
    assert rules.coverage([None, None], [None]) == pytest.approx(0.5)


def test_segment_speed_below_coverage_is_missing() -> None:
    speed, flag = rules.segment_speed([500.0, 700.0], [(500.0, 61.0)], 0.7)
    assert (speed, flag) == (None, "missing")  # 41.7%


def test_segment_speed_partial_and_ok() -> None:
    speed, flag = rules.segment_speed([500.0, 50.0], [(500.0, 60.0)], 0.7)  # 90.9%
    assert speed == pytest.approx(60.0)
    assert flag == "partial"

    speed, flag = rules.segment_speed([500.0, 700.0], [(500.0, 60.0), (700.0, 70.0)], 0.7)
    assert speed == pytest.approx(1200 / (500 / 60 + 700 / 70))
    assert flag == "ok"


def test_segment_speed_unweighted_when_length_unknown() -> None:
    speed, flag = rules.segment_speed([800.0, None], [(800.0, 40.0), (None, 50.0)], 0.7)
    assert speed == pytest.approx(45.0)
    assert flag == "unweighted"


def test_segment_speed_at_exact_coverage_boundary() -> None:
    # 기준은 "미만이면 missing"이므로 0.7과 정확히 같으면 산출한다.
    speed, flag = rules.segment_speed([700.0, 300.0], [(700.0, 60.0)], 0.7)
    assert (speed, flag) == (60.0, "partial")


def test_segment_speed_missing_inputs() -> None:
    assert rules.segment_speed([], [], 0.7) == (None, "missing")
    assert rules.segment_speed([500.0], [], 0.7) == (None, "missing")


def test_fill_source_uses_immediately_previous_real_bin() -> None:
    assert rules.fill_source(["ok"], 2) == 0
    assert rules.fill_source(["ok", "missing"], 2) == 0


def test_fill_source_limits_run_length() -> None:
    # 현재 bin을 포함한 연속 결측이 max_bins를 넘으면 채우지 않는다.
    assert rules.fill_source(["ok", "missing", "missing"], 2) is None  # 3번째 결측
    assert rules.fill_source(["missing"], 2) is None  # 앞선 근거 bin이 목록에 없음


def test_fill_source_never_uses_imputed() -> None:
    # imputed는 결측 길이에 세고 근거로 쓰지 않는다.
    assert rules.fill_source(["ok", "imputed"], 2) == 0
    assert rules.fill_source(["imputed", "imputed"], 2) is None
