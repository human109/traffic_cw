"""R-09 보조: 도로명 정확 일치 링크 전체를 노드 이름과 함께 출력한다(탐색용).

사용: python -I dump_road_links_named.py <extract_road_links.py 출력 JSON> <출력 텍스트> [도로명]
"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
d = json.load(open(sys.argv[1], encoding="utf-8"))
nodes = d["nodes"]
road = sys.argv[3] if len(sys.argv) > 3 else "원이대로"
links = [l for l in d["links"] if l["ROAD_NAME"] == road]


def nn(nid):
    n = nodes.get(nid)
    return n["NODE_NAME"] if n else "?"


with open(sys.argv[2], "w", encoding="utf-8") as out:
    out.write(f"{road} 정확 일치 링크 {len(links)}개\n")
    out.write("LINK_ID F_NODE 이름 -> T_NODE 이름 LENGTH(m) rt lanes spd\n")
    for l in sorted(links, key=lambda x: (x["F_NODE"], x["T_NODE"])):
        out.write(f"{l['LINK_ID']} {l['F_NODE']} {nn(l['F_NODE'])} -> {l['T_NODE']} {nn(l['T_NODE'])} "
                  f"{float(l['LENGTH']):.1f} {l['ROAD_TYPE']} {l['LANES']} {l['MAX_SPD']}\n")
print("written", sys.argv[2])
