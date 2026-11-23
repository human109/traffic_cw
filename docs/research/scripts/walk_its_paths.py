"""R-09 보조: ITS 원이대로 체인의 모든 단순 경로를 DFS로 탐색한다(탐색용).

사용: python -I walk_its_paths.py <its_wonidaero_raw_items.csv> <출력 텍스트> <시작 ITS 노드>
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8")))
out = open(sys.argv[2], "w", encoding="utf-8")
w = lambda s="": out.write(s + "\n")  # noqa: E731

edge = {}
for r in rows:
    edge.setdefault((r["start_node"], r["end_node"]), r["link_id"])
out_edges = defaultdict(list)
for (s, e), lid in edge.items():
    out_edges[s].append((e, lid))

start = sys.argv[3]
paths = []


def dfs(node, path, visited):
    nxt = [(e, lid) for e, lid in out_edges.get(node, []) if e not in visited]
    if not nxt or len(paths) > 30:
        paths.append(list(path))
        return
    for e, lid in nxt:
        visited.add(e)
        path.append((node, e, lid))
        dfs(e, path, visited)
        path.pop()
        visited.discard(e)


dfs(start, [], {start})
w(f"시작 {start}: 경로 {len(paths)}개")
for p in paths:
    w(f"-- 길이 {len(p)} : " + " -> ".join(f"{e}({lid})" for _s, e, lid in p))
out.close()
print("written", sys.argv[2])
