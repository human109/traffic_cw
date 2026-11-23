"""R-09 보조: 원이대로 후보 노드(명곡, 가음정) 주변의 링크·노드를 검사한다(탐색용).

사용: python -I inspect_wonidaero_nodes.py <extract_road_links.py 출력 JSON> <출력 텍스트 경로>
표준 라이브러리만 사용한다. 원본 읽기 전용.
"""
import json
import math
import sys

sys.stdout.reconfigure(encoding="utf-8")
d = json.load(open(sys.argv[1], encoding="utf-8"))
nodes = d["nodes"]
links = d["links"]


def nn(nid):
    n = nodes.get(nid)
    return n["NODE_NAME"] if n else "?"


def hdg(l):
    (x0, y0), (x1, y1) = l["_start"], l["_end"]
    return math.degrees(math.atan2(x1 - x0, y1 - y0)) % 360


def heading_of_out(l):
    return hdg(l)


out = open(sys.argv[2], "w", encoding="utf-8")

# 1. 원이대로 정확 일치 링크의 노드별 연결 요약
exact = [l for l in links if l["ROAD_NAME"] == "원이대로"]
out.write(f"원이대로 정확 일치 링크: {len(exact)}개\n\n")

# 노드 이름에서 키워드로 시작 노드 후보를 찾는다
for kw in ("명곡", "가음정"):
    out.write(f"== '{kw}' 이름 노드와 그 노드에 접한 링크\n")
    for nid in sorted(nodes):
        if kw in nn(nid):
            out.write(f"  노드 {nid} {nn(nid)} type={nodes[nid]['NODE_TYPE']}\n")
            for l in exact:
                if l["F_NODE"] == nid or l["T_NODE"] == nid:
                    arrow = "->" if l["F_NODE"] == nid else "<-"
                    other = l["T_NODE"] if l["F_NODE"] == nid else l["F_NODE"]
                    out.write(f"      {l['LINK_ID']} {arrow} {other} {nn(other)} "
                              f"len={float(l['LENGTH']):.1f} rt={l['ROAD_TYPE']} "
                              f"lanes={l['LANES']} spd={l['MAX_SPD']} hdg={hdg(l):.0f}\n")
    out.write("\n")

# 2. 인접(이름 불일치) 링크가 잇는 노드쌍 중 명곡/가음정 주변
out.write("== 원이대로 링크와 같은 노드를 공유하는 인접 링크(도로명 불일치) 중 가음정·명곡 관련\n")
exact_nodes = {l["F_NODE"] for l in exact} | {l["T_NODE"] for l in exact}
for l in links:
    if l["_match"] != "adjacent":
        continue
    if l["F_NODE"] in exact_nodes or l["T_NODE"] in exact_nodes:
        if "가음정" in nn(l["F_NODE"]) or "가음정" in nn(l["T_NODE"]) or \
           "명곡" in nn(l["F_NODE"]) or "명곡" in nn(l["T_NODE"]):
            out.write(f"  {l['LINK_ID']} {l['ROAD_NAME']} {l['F_NODE']} {nn(l['F_NODE'])} -> "
                      f"{l['T_NODE']} {nn(l['T_NODE'])} len={float(l['LENGTH']):.1f} "
                      f"rt={l['ROAD_TYPE']} conn={l['CONNECT']} hdg={hdg(l):.0f}\n")

out.close()
print("written", sys.argv[2])
