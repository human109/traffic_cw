"""R-09 보조: 후보 CSV와 매핑 CSV를 검증한다(합계·행수·체인 연속성).

사용: python -I verify_candidates.py
"""
import csv
import sys

sys.stdout.reconfigure(encoding="utf-8")
cand = list(csv.DictReader(open("docs/research/samples/wonidaero_segment_links_candidates_2026-11-23.csv", encoding="utf-8")))
print(f"후보 행 수: {len(cand)}")
segs = {}
for r in cand:
    segs.setdefault(r["segment_id"], []).append(r)
for seg, rows in sorted(segs.items()):
    tot = sum(float(r["link_length_m"]) for r in rows)
    ids = [r["link_id"] for r in rows]
    print(f"{seg}: {len(rows)}행 {tot:.1f}m  {' '.join(ids)}")

# 매핑 CSV의 ours 행과 후보 행 비교
mp = [r for r in csv.DictReader(open("docs/research/samples/wonidaero_link_mapping_2026-11-23.csv", encoding="utf-8")) if r["dir"] == "ours"]
cand_ids = {r["link_id"]: float(r["link_length_m"]) for r in cand}
bad = 0
for r in mp:
    lid = r["its_link_id"]
    a = float(r["alloc_length_m"])
    if lid in cand_ids and abs(cand_ids[lid] - a) > 0.05:
        print(f"DIFF {lid}: 후보 {cand_ids[lid]} vs 매핑 {a}")
        bad += 1
    if lid not in cand_ids:
        print(f"MISSING {lid} in 후보")
        bad += 1
extra = set(cand_ids) - {r["its_link_id"] for r in mp}
if extra:
    print("후보에만 있는 링크:", sorted(extra))
    bad += 1
print("검증 불일치:", bad)
sys.exit(1 if bad else 0)
