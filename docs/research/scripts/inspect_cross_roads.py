"""R-09 보조: 원이대로 주요 교차로 노드에 접한 원이대로 외 링크(교차 도로)를 검사한다(탐색용).

사용: python -I inspect_cross_roads.py <extract_road_links.py 출력 JSON> <출력 텍스트>
"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
d = json.load(open(sys.argv[1], encoding="utf-8"))
nodes = d["nodes"]
links = d["links"]
exact_nodes = set()
for l in links:
    if l["ROAD_NAME"] == "원이대로":
        exact_nodes.add(l["F_NODE"])
        exact_nodes.add(l["T_NODE"])


def nn(nid):
    n = nodes.get(nid)
    return n["NODE_NAME"] if n else "?"


# 교차로 후보: 이름에 사거리/삼거리/교차로/광장/교 가 들어가는 노드
out = open(sys.argv[2], "w", encoding="utf-8")
seen_group = set()
for nid in sorted(exact_nodes):
    name = nn(nid)
    if not any(k in name for k in ("사거리", "삼거리", "교차로", "광장", "교", "노총", "체육관", "은행", "환경", "중학교", "경륜", "시청")):
        continue
    key = name.split("(")[0]
    if key in seen_group:
        continue
    seen_group.add(key)
    out.write(f"== {name}\n")
    for l in links:
        if l["F_NODE"] == nid or l["T_NODE"] == nid:
            if l["ROAD_NAME"] == "원이대로":
                continue
            other = l["T_NODE"] if l["F_NODE"] == nid else l["F_NODE"]
            out.write(f"   {l['LINK_ID']} {l['ROAD_NAME']} {'나감' if l['F_NODE']==nid else '들어옴'} "
                      f"-> {other} {nn(other)} len={float(l['LENGTH']):.1f} rt={l['ROAD_TYPE']}\n")
    # 좌표
    n = nodes.get(nid)
    if n and n.get("_xy"):
        out.write(f"   좌표 ({n['_xy'][0]:.0f}, {n['_xy'][1]:.0f})\n")
out.close()
print("written", sys.argv[2])
