"""R-09 보조: ITS 원본 item에서 원이대로 방향 체인을 노드 연결로 직접 탐색한다(탐색용).

사용: python -I walk_its_chain.py <its_wonidaero_raw_items.csv> <출력 텍스트> <시작 ITS 노드>
시작 노드에서 나가는 원이대로 링크를 따라가 끝까지 간다(분기는 모두 출력).
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8")))
out = open(sys.argv[2], "w", encoding="utf-8")

edge = {}  # (start, end) → link_id (첫 관측)
nodes_of = defaultdict(set)
for r in rows:
    edge.setdefault((r["start_node"], r["end_node"]), r["link_id"])
    nodes_of[r["start_node"]].add(r["end_node"])

start = sys.argv[3]
out_edges = defaultdict(list)
for (s, e), lid in edge.items():
    out_edges[s].append((e, lid))

cur = start
visited = set()
w = lambda s="": out.write(s + "\n")  # noqa: E731
w(f"시작 {start}에서 나가는 원이대로 체인:")
while True:
    nxt = out_edges.get(cur, [])
    w(f"  {cur} → " + (", ".join(f"{e}({lid})" for e, lid in nxt) or "(끝)"))
    if len(nxt) != 1 or cur in visited:
        break
    visited.add(cur)
    cur = nxt[0][0]
w(f"끝: {cur}")
out.close()
print("written", sys.argv[2])
