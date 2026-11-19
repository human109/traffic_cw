"""`config/segment_links.csv`를 만든다.

입력: docs/research/samples/changwondaero_links_2026-11-11.csv (R-03b, 표준노드링크 2026-11-11 배포본)
규칙 (Ruling 2026-11-19, 근거: 첫 ITS 실측 — docs/tasks/BOARD.md 결정 기록):
  ITS는 분할 전 링크(ID 끝 `00`)로 속도·통행시간을 준다. `속도 x 통행시간`으로 역산한 길이가
  배포본의 분할 링크(`…01`, `…02` …) 길이 합과 일치했다.
  → 같은 구간 안에서 분할 링크는 부모 링크(앞 8자리 + `00`)에 합치고 길이를 더한다.
  → 부모가 다른 구간에 있는 분할 링크(교차로 내부 약 12m)는 버린다.
  → 부모가 체인에 없는 링크는 그대로 둔다(관측되지 않을 수 있음).
  거리 가중 조화평균에서 같은 속도를 가진 링크들을 합치는 것은 결과가 같으므로 계산이 바뀌지 않는다.

실행: .venv\\Scripts\\python -m config.build_segment_links
"""

from __future__ import annotations

import csv
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "research" / "samples" / "changwondaero_links_2026-11-11.csv"
DST = ROOT / "config" / "segment_links.csv"
COLS = ["segment_id", "seq", "link_id", "source", "link_length_m", "is_mainline", "nodelink_ver", "valid_from"]
LINK_SOURCE = "moct_nodelink"

# R-03b 8구간 → v1.3 6구간 (SPEC 3.3)
def _new_segment(old: str, seq: int) -> str:
    return {
        "S0": "S0", "S1": "S1", "S2": "S1", "S3": "S2",
        "S5": "S4", "S6": "S5", "S7": "S6",
    }.get(old) or ("S3" if seq <= 17 else "S4")


# ITS가 2026 배포본과 다른(개정 이전) ID로 주는 링크: 배포본 ID → ITS ID (길이는 배포본 값 유지)
# 근거: docs/research/R-06b-link-fix-and-direction.md 수정안 1
ITS_ID_OVERRIDES: dict[str, str] = {"4140068801": "4140068800"}


def parent_id(link_id: str) -> str:
    return link_id[:8] + "00"


def build() -> list[dict]:
    with SRC.open(encoding="utf-8", newline="") as f:
        rows = [{**r, "segment_id": _new_segment(r["segment_id"], int(r["seq"]))} for r in csv.DictReader(f)]

    seg_of = {r["link_id"]: r["segment_id"] for r in rows}

    def is_child(lid: str) -> bool:
        return lid != parent_id(lid) and parent_id(lid) in seg_of

    merged: "OrderedDict[tuple[str, str], dict]" = OrderedDict()
    for r in rows:  # 1단계: 부모·독립 링크
        if not is_child(r["link_id"]):
            merged[(r["segment_id"], r["link_id"])] = {k: r[k] for k in COLS} | {"source": LINK_SOURCE}
    for r in rows:  # 2단계: 분할 링크 길이를 같은 구간의 부모에 더함
        lid, seg = r["link_id"], r["segment_id"]
        if is_child(lid) and seg_of[parent_id(lid)] == seg:
            key = (seg, parent_id(lid))
            merged[key]["link_length_m"] = f"{float(merged[key]['link_length_m']) + float(r['link_length_m']):.1f}"

    out, seq = [], {}
    for (seg, _), r in merged.items():
        seq[seg] = seq.get(seg, 0) + 1
        out.append(r | {"seq": seq[seg], "link_id": ITS_ID_OVERRIDES.get(r["link_id"], r["link_id"])})
    return out


def main() -> None:
    out = build()
    with DST.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"{DST.name}: {len(out)} links")


if __name__ == "__main__":
    main()
