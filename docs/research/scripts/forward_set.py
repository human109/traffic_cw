"""시작 노드에서 끝 노드 집합까지 가는 경로 위의 도로명 일치 링크(정방향 집합)를 구한다(탐색용).

사용: python -I forward_set.py <JSON> <시작 NODE_ID> <끝 NODE_ID,...> [도로명]

정방향 집합 = (시작에서 도달 가능한 링크) ∩ (끝 노드에 도달할 수 있는 링크).
끝 노드에서 더 나가는 링크는 따라가지 않는다. 인접 링크 중 정방향 집합의 노드 두 개를
잇는 링크(도로명 불일치 지하차도 등)도 함께 출력한다.
"""
import json
import math
import sys

sys.stdout.reconfigure(encoding="utf-8")
d = json.load(open(sys.argv[1], encoding="utf-8"))
S = sys.argv[2]
E = set(sys.argv[3].split(","))
road = sys.argv[4] if len(sys.argv) > 4 else "창원대로"
nodes = d["nodes"]
links = [l for l in d["links"] if l["ROAD_NAME"] == road]
out, inn = {}, {}
for l in links:
    out.setdefault(l["F_NODE"], []).append(l)
    inn.setdefault(l["T_NODE"], []).append(l)


def nn(nid):
    n = nodes.get(nid)
    return n["NODE_NAME"] if n else "?"


def hdg(l):
    (x0, y0), (x1, y1) = l["_start"], l["_end"]
    return math.degrees(math.atan2(x1 - x0, y1 - y0)) % 360


reach, stack = {S}, [S]
while stack:
    n = stack.pop()
    if n in E:
        continue
    for l in out.get(n, []):
        if l["T_NODE"] not in reach:
            reach.add(l["T_NODE"])
            stack.append(l["T_NODE"])
co, stack = set(E), list(E)
while stack:
    n = stack.pop()
    for l in inn.get(n, []):
        if l["F_NODE"] not in co and l["F_NODE"] not in E:
            co.add(l["F_NODE"])
            stack.append(l["F_NODE"])
fwd = [l for l in links if l["F_NODE"] in reach and l["T_NODE"] in co and l["F_NODE"] not in E]
fnodes = {l["F_NODE"] for l in fwd} | {l["T_NODE"] for l in fwd}
print("forward links", len(fwd))
for l in sorted(fwd, key=lambda l: l["LINK_ID"]):
    print(l["LINK_ID"], l["F_NODE"], nn(l["F_NODE"]), "->", l["T_NODE"], nn(l["T_NODE"]),
          f'{float(l["LENGTH"]):.1f}', l["ROAD_TYPE"], l["LANES"], l["MAX_SPD"], f"hdg={hdg(l):.0f}")
print("== 인접 링크 중 정방향 노드끼리 잇거나 지하차도·교량인 것")
for l in d["links"]:
    if l["_match"] != "adjacent":
        continue
    both = l["F_NODE"] in fnodes and l["T_NODE"] in fnodes
    if both or (l["ROAD_TYPE"] != "000" and (l["F_NODE"] in fnodes or l["T_NODE"] in fnodes)):
        print(l["LINK_ID"], l["ROAD_NAME"], l["F_NODE"], nn(l["F_NODE"]), "->", l["T_NODE"],
              nn(l["T_NODE"]), f'{float(l["LENGTH"]):.1f}', l["ROAD_TYPE"], l["CONNECT"],
              l["LANES"], l["MAX_SPD"], f"hdg={hdg(l):.0f}", "both" if both else "")
# 노드 분기 점검: 정방향 집합에서 나가는 링크가 2개 이상인 노드
print("== 분기 노드")
fo = {}
for l in fwd:
    fo.setdefault(l["F_NODE"], []).append(l["LINK_ID"])
for n, ls in fo.items():
    if len(ls) > 1:
        print(n, nn(n), ls)
