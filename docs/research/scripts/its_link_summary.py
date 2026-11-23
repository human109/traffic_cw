"""R-09 보조: extract_its_road.py 출력 CSV에서 링크별 요약(회차 수, 노드쌍, 역산 길이)을 만든다.

사용: python -I its_link_summary.py <CSV> <출력 텍스트>
표준 라이브러리만 사용한다.
"""
import csv
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8")))
out = open(sys.argv[2], "w", encoding="utf-8")

by_link = defaultdict(list)
for r in rows:
    by_link[r["link_id"]].append(r)

out.write(f"rows={len(rows)} links={len(by_link)}\n\n")
out.write("link_id | start_node | end_node | 회차 | speed 범위 | 역산길이(m) 평균(최소~최대)\n")
stats = {}
for lid, rs in by_link.items():
    sn, en = rs[0]["start_node"], rs[0]["end_node"]
    n = len(rs)
    speeds = [float(r["speed"]) for r in rs if r["speed"]]
    lengths = []
    for r in rs:
        try:
            sp, tt = float(r["speed"]), float(r["travel_time"])
            if sp > 0 and tt > 0:
                lengths.append(sp * tt / 3.6)
        except ValueError:
            pass
    lmean = sum(lengths) / len(lengths) if lengths else 0.0
    lmin = min(lengths) if lengths else 0.0
    lmax = max(lengths) if lengths else 0.0
    stats[lid] = (sn, en, n, min(speeds), max(speeds), lmean, lmin, lmax)

for lid in sorted(stats):
    sn, en, n, smin, smax, lm, ln, lx = stats[lid]
    out.write(f"{lid} | {sn} | {en} | {n} | {smin:.1f}~{smax:.1f} | {lm:.1f} ({ln:.1f}~{lx:.1f})\n")

# created_date 회차 요약
dates = sorted({r["created_date"] for r in rows})
out.write(f"\ncreated_date 회차 수: {len(dates)} (첫 {dates[0]}, 마지막 {dates[-1]})\n")
out.close()
print("written", sys.argv[2])
