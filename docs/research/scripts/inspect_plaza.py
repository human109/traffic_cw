"""R-09 보조: 창원광장 로터리 내부(원이대로 링크가 끊기는 구간)를 검사한다(탐색용).

사용: python -I inspect_plaza.py <extract_road_links.py 출력 JSON> <출력 텍스트>
"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
d = json.load(open(sys.argv[1], encoding="utf-8"))
nodes = d["nodes"]
links = d["links"]
TARGETS = ["4150022803", "4150022804", "4150025801", "4150025802",
           "4150021801", "4150021802", "4150027403", "4150027404"]


def nn(nid):
    n = nodes.get(nid)
    return n["NODE_NAME"] if n else "?"


out = open(sys.argv[2], "w", encoding="utf-8")
for nid in TARGETS:
    n = nodes.get(nid)
    xy = f"({n['_xy'][0]:.0f}, {n['_xy'][1]:.0f})" if n and n.get("_xy") else "(JSON에 없음)"
    out.write(f"== {nid} {nn(nid)} {xy}\n")
    for l in links:
        if l["F_NODE"] == nid or l["T_NODE"] == nid:
            other = l["T_NODE"] if l["F_NODE"] == nid else l["F_NODE"]
            arrow = "나감" if l["F_NODE"] == nid else "들어옴"
            out.write(f"   {l['LINK_ID']} {l['ROAD_NAME']} {arrow} -> {other} {nn(other)} "
                      f"len={float(l['LENGTH']):.1f} rt={l['ROAD_TYPE']}\n")
out.close()
print("written", sys.argv[2])
