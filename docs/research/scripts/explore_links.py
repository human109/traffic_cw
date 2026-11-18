"""extract_road_links.py 출력 JSON의 개요를 출력한다(탐색용).

사용: python -I explore_links.py <JSON>
"""
import collections
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
d = json.load(open(sys.argv[1], encoding="utf-8"))
links = d["links"]
nodes = d["nodes"]
named = [l for l in links if l["_match"] != "adjacent"]
print("match counts", collections.Counter(l["_match"] for l in links))
print("prefix", collections.Counter(l["LINK_ID"][:3] for l in named))
for k in ("ROAD_TYPE", "ROAD_RANK", "ROAD_USE", "CONNECT", "ROAD_NAME", "MAX_SPD", "LANES"):
    print(k, collections.Counter(l[k] for l in named))
xs = [l["_start"][0] for l in named]
ys = [l["_start"][1] for l in named]
print("bbox", min(xs), max(xs), min(ys), max(ys))
print("total LENGTH", sum(float(l["LENGTH"]) for l in named))
nm = collections.Counter()
for l in named:
    for k in ("F_NODE", "T_NODE"):
        n = nodes.get(l[k])
        nm[(n["NODE_NAME"], n["NODE_TYPE"]) if n else "?"] += 1
for k, v in sorted(nm.items(), key=str):
    print(" ", k, v)
