"""extract_road_links.py 출력에서 도로명 일치 링크의 진행 방향 경로를 추적한다(탐색용).

사용: python -I trace_chain.py <JSON> <시작 노드명 일부> [도로명]

- 도로명이 정확히 일치하는 링크만 그래프에 넣는다.
- 시작 노드명에 해당하는 노드에서 나가는 링크마다, 역방향(바로 돌아오는 링크)을 빼고
  도달 가능한 모든 단순 경로를 깊이 우선으로 펼친다(분기 확인용).
"""
import json
import math
import sys

sys.stdout.reconfigure(encoding="utf-8")
d = json.load(open(sys.argv[1], encoding="utf-8"))
start_kw = sys.argv[2]
road = sys.argv[3] if len(sys.argv) > 3 else "창원대로"
nodes = d["nodes"]
links = [l for l in d["links"] if l["ROAD_NAME"] == road]
out = {}
for l in links:
    out.setdefault(l["F_NODE"], []).append(l)


def nn(nid):
    n = nodes.get(nid)
    return n["NODE_NAME"] if n else "?"


def heading(l):
    (x0, y0), (x1, y1) = l["_start"], l["_end"]
    return math.degrees(math.atan2(x1 - x0, y1 - y0)) % 360


print("== 도로명 일치 링크 전체")
for l in sorted(links, key=lambda l: l["LINK_ID"]):
    print(l["LINK_ID"], l["F_NODE"], nn(l["F_NODE"]), "->", l["T_NODE"], nn(l["T_NODE"]),
          f'{float(l["LENGTH"]):.1f}', f'geom={l["_geom_len"]:.1f}', l["ROAD_TYPE"], l["LANES"],
          l["MAX_SPD"], f"hdg={heading(l):.0f}")

starts = [nid for nid, n in nodes.items() if start_kw in n["NODE_NAME"]]
print("== 시작 노드 후보", [(s, nn(s)) for s in starts])
paths = []


def dfs(node, path, visited):
    nxt = [l for l in out.get(node, []) if l["T_NODE"] not in visited]
    if path:
        prev = path[-1]
        nxt = [l for l in nxt if l["T_NODE"] != prev["F_NODE"]]
    if not nxt or len(paths) > 50:
        paths.append(list(path))
        return
    for l in nxt:
        path.append(l)
        visited.add(l["T_NODE"])
        dfs(l["T_NODE"], path, visited)
        visited.discard(l["T_NODE"])
        path.pop()


for s in starts:
    for l in out.get(s, []):
        dfs(l["T_NODE"], [l], {s, l["T_NODE"]})
print("== 경로 수", len(paths))
for p in paths:
    tot = sum(float(l["LENGTH"]) for l in p)
    print(f"-- links={len(p)} len={tot:.0f} first={p[0]['LINK_ID']} hdg0={heading(p[0]):.0f} end={nn(p[-1]['T_NODE'])}")
    print("   " + " | ".join(f"{l['LINK_ID']}:{nn(l['T_NODE'])}({l['ROAD_TYPE']})" for l in p))
