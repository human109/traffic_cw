"""분석 구간 시드 (SPEC 3.3). DB `road_segment` 초기 적재용이며, 기준 원본은 DB다 (SPEC 3.5).

구간 경계는 후보이며 표준노드링크 확인(R-03b) 후 조정한다. 링크 매핑은 `config/segment_links.csv`.
"""

from __future__ import annotations

_ROAD = "창원대로"
_DIRECTION = "팔용동→창원터널 방면"

_BOUNDS = [
    ("S0", "소계광장 교차로", "팔용사거리"),
    ("S1", "팔용사거리", "평산사거리"),
    ("S2", "평산사거리", "차룡사거리"),
    ("S3", "차룡사거리", "용원교차로"),
    ("S4", "용원교차로", "교육단지사거리"),
    ("S5", "교육단지사거리", "공단본부삼거리"),
    ("S6", "공단본부삼거리", "가음정사거리"),
    ("S7", "가음정사거리", "성주광장 교차로"),
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
