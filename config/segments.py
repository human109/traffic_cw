"""분석 구간 시드. DB `road_segment` 초기 적재용이며, 기준 원본은 DB다 (SPEC 3.5).

v1.3 재편(R-03b 권장안): 표준노드링크 2026-11-11 배포본 기준, 예측 구간 6개가 모두 1.17~2.05km.
링크 매핑은 `config/segment_links.csv` (근거: docs/research/samples/changwondaero_links_2026-11-11.csv).
"""

from __future__ import annotations

_ROAD = "창원대로"
_DIRECTION = "팔용동→창원터널 방면"

_BOUNDS = [
    ("S0", "소계광장교차로", "팔용사거리"),
    ("S1", "팔용사거리", "차룡사거리"),
    ("S2", "차룡사거리", "용원지하차도(서측)"),
    ("S3", "용원지하차도(서측)", "삼동지하차도(동측)"),
    ("S4", "삼동지하차도(동측)", "공단본부삼거리"),
    ("S5", "공단본부삼거리", "가음정사거리"),
    ("S6", "가음정사거리", "성주광장"),
]

SEGMENTS: list[dict] = [
    {
        "segment_id": sid,
        "seq": i,
        "start_node": start,
        "end_node": end,
        "road_name": _ROAD,
        "direction": _DIRECTION,
        "is_target": 0 if sid == "S0" else 1,
    }
    for i, (sid, start, end) in enumerate(_BOUNDS)
]
