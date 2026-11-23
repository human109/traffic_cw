"""R-09 보조: 지정 노드 ID의 좌표를 텍스트로 출력한다(탐색용).

사용: python -I dump_node_xy.py <extract_road_links.py 출력 JSON> <출력 텍스트> <NODE_ID,...>
"""
import json
import sys

d = json.load(open(sys.argv[1], encoding="utf-8"))
nodes = d["nodes"]
ids = sys.argv[3].split(",")
out = []
for nid in ids:
    n = nodes.get(nid)
    if n and n.get("_xy"):
        out.append(f"{nid} {n['NODE_NAME']} ({n['_xy'][0]:.0f}, {n['_xy'][1]:.0f}) type={n['NODE_TYPE']}")
with open(sys.argv[2], "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("written", sys.argv[2])
