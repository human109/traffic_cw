"""분석 구간 시드. DB `road_segment` 초기 적재용이며, 기준 원본은 DB다 (SPEC 3.5).

v1.3 재편(R-03b 권장안): 표준노드링크 2026-11-11 배포본 기준, 창원대로 예측 구간 6개가 모두 1.17~2.05km.
v1.4(R-09): 원이대로 W0~W5 추가. 도로 구분은 `road_name`이다.
링크 매핑은 `config/segment_links.csv` (근거: docs/research/samples/changwondaero_links_2026-11-11.csv,
docs/research/samples/wonidaero_segment_links_candidates_2026-11-23.csv).

`is_target`: 도로가 `settings.target_corridors`에 있고 참고 구간(S0, W0)이 아니면 1.
"""

from __future__ import annotations

from config.settings import Settings

REFERENCE_SEGMENTS = frozenset({"S0", "W0"})

# 도로 → (방향, [(구간 ID, 시작, 끝)])
_ROADS: dict[str, tuple[str, list[tuple[str, str, str]]]] = {
    "창원대로": (
        "팔용동→창원터널 방면",
        [
            ("S0", "소계광장교차로", "팔용사거리"),
            ("S1", "팔용사거리", "차룡사거리"),
            ("S2", "차룡사거리", "용원지하차도(서측)"),
            ("S3", "용원지하차도(서측)", "삼동지하차도(동측)"),
            ("S4", "삼동지하차도(동측)", "공단본부삼거리"),
            ("S5", "공단본부삼거리", "가음정사거리"),
            ("S6", "가음정사거리", "성주광장"),
        ],
    ),
    "원이대로": (
        "명곡교→가음정사거리 방면",
        [
            ("W0", "목련삼거리", "명곡교(서측)"),
            ("W1", "명곡교(서측)", "중앙중사거리"),
            ("W2", "중앙중사거리", "용지사거리"),
            ("W3", "용지사거리", "한국은행사거리"),
            ("W4", "한국은행사거리", "성원아파트사거리"),
            ("W5", "성원아파트사거리", "가음정사거리"),
        ],
    ),
}


def build_segments(target_corridors: tuple[str, ...]) -> list[dict]:
    """`road_segment` 시드 행. `seq`는 도로 안 순서(0부터)다."""
    rows: list[dict] = []
    for road, (direction, bounds) in _ROADS.items():
        for i, (sid, start, end) in enumerate(bounds):
            rows.append(
                {
                    "segment_id": sid,
                    "seq": i,
                    "start_node": start,
                    "end_node": end,
                    "road_name": road,
                    "direction": direction,
                    "is_target": int(road in target_corridors and sid not in REFERENCE_SEGMENTS),
                }
            )
    return rows


SEGMENTS: list[dict] = build_segments(Settings.target_corridors)
