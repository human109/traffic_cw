"""전처리 판정 규칙 (SPEC 6.2~6.4, C-01 v1.2). DB를 모르는 순수 함수만 둔다.

- `frozen_mask`: 갱신 정지 판정
- `segment_speed`: 커버리지 기준 + 거리 가중 조화평균 / 단순 평균
- `fill_source`: 짧은 결측 보정에 쓸 직전 실제 bin 찾기
"""

from __future__ import annotations

from collections.abc import Sequence

REAL_FLAGS = frozenset({"ok", "partial", "unweighted"})
"""실제 관측으로 계산된 bin의 quality_flag. `missing`·`imputed`는 보정 근거가 될 수 없다."""

_EPS = 1e-9


def frozen_mask(speeds: Sequence[float], repeat_count: int) -> list[bool]:
    """원본 시각이 서로 다른 관측의 speed를 시간순으로 받아, 갱신 정지로 뺄 관측을 True로 표시한다.

    같은 speed가 `repeat_count`회 이상 연속이면 `repeat_count`번째 관측부터 True다.
    원본 시각이 같은 반복은 호출 전에 하나로 합쳐야 한다(그런 반복은 갱신 정지가 아니다).
    """
    mask: list[bool] = []
    run = 0
    prev: float | None = None
    for s in speeds:
        run = run + 1 if prev is not None and s == prev else 1
        prev = s
        mask.append(run >= repeat_count)
    return mask


def coverage(expected_lengths: Sequence[float | None], observed_lengths: Sequence[float | None]) -> float:
    """관측 비율. 기대 링크 길이를 모두 알면 길이 기준, 하나라도 모르면 링크 수 기준."""
    if not expected_lengths:
        return 0.0
    if all(l is not None for l in expected_lengths) and all(l is not None for l in observed_lengths):
        total = sum(expected_lengths)  # type: ignore[arg-type]
        if total > 0:
            return sum(observed_lengths) / total  # type: ignore[arg-type]
    return len(observed_lengths) / len(expected_lengths)


def segment_speed(
    expected_lengths: Sequence[float | None],
    observed: Sequence[tuple[float | None, float]],
    min_coverage: float,
) -> tuple[float | None, str]:
    """구간 속도와 quality_flag를 돌려준다.

    Args:
        expected_lengths: 이 bin에 유효한 링크 전체의 길이(모르면 None)
        observed: 관측된 링크의 (길이, speed). speed는 0보다 커야 한다.
        min_coverage: 관측 비율 하한(`partial_min_coverage`)

    Returns:
        - 관측 없음·비율 미달: `(None, "missing")`
        - 관측 링크 중 길이 모름이 있으면 단순 평균, `"unweighted"`
        - 그 밖에는 `Σlen / Σ(len/speed)`, 전부 관측이면 `"ok"`, 아니면 `"partial"`
    """
    if not expected_lengths or not observed:
        return None, "missing"
    if coverage(expected_lengths, [l for l, _ in observed]) + _EPS < min_coverage:
        return None, "missing"
    if any(l is None for l, _ in observed):
        return sum(s for _, s in observed) / len(observed), "unweighted"
    total_len = sum(l for l, _ in observed)  # type: ignore[misc]
    total_time = sum(l / s for l, s in observed)  # type: ignore[operator]
    flag = "ok" if len(observed) == len(expected_lengths) else "partial"
    return total_len / total_time, flag


def fill_source(prev_flags: Sequence[str], max_bins: int) -> int | None:
    """결측 bin을 채울 근거가 되는 직전 실제 bin의 인덱스를 돌려준다. 채울 수 없으면 None.

    `prev_flags`는 현재 bin 바로 앞의 bin들(오래된 것 → 최근, 빈틈 없이)이다. 현재 bin을 포함한
    연속 결측(`missing`·`imputed`) 길이가 `max_bins` 이하이고, 그 바로 앞 bin이 실제 값일 때만 채운다.
    보정값(`imputed`)은 근거로 쓰지 않고 결측 길이에 센다. 연속 결측 길이는 현재 bin까지만 센다
    (뒤의 bin을 보지 않으므로 미래 정보를 쓰지 않는다).
    """
    run = 1
    i = len(prev_flags) - 1
    while i >= 0 and prev_flags[i] not in REAL_FLAGS:
        run += 1
        if run > max_bins:
            return None
        i -= 1
    if run > max_bins or i < 0:
        return None
    return i
