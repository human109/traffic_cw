"""창원대로 출근 방향(소계광장→성주광장) 링크 표를 만든다. 표준 라이브러리만 사용.

입력: extract_road_links.py 출력 JSON (2026-11-11 배포본에서 추출)
출력: segment_link 시드 후보 CSV (UTF-8)

사용: python -I build_changwondaero_table.py <JSON> <출력 CSV>

구간 경계 노드는 파일에서 읽은 NODE_ID다(R-03b 문서 참조). 경계는 교차로 '진입 노드'
(상류 쪽 노드)로 두고, 교차로 내부 링크는 그 교차로에서 시작하는 하류 구간에 넣는다.
지하차도 분기점에서는 ROAD_TYPE='002' 쪽을 본선(is_mainline=1), 다른 쪽을 측도(0)로 둔다.
"""
import csv
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROAD = "창원대로"
START = "4140026303"  # 소계광장교차로 (정방향 진입)
ENDS = {"4150043302", "4150043306"}  # 20교차로성주광장교차로 (본선 / 측도 도착)
# (구간 ID, 구간 시작 노드) — 각 구간은 다음 구간 시작 노드에서 끝난다.
BOUNDARIES = [
    ("S0", "4140026303"),  # 소계광장교차로
    ("S1", "4140031303"),  # 팔용사거리 진입
    ("S2", "4140035503"),  # 평산사거리 진입
    ("S3", "4140040903"),  # 차룡사거리 진입
    ("S4", "4140051202"),  # 용원지하차도(서측) 분기점 (용원교차로 상류)
    ("S5", "4150017103"),  # 교육단지사거리 진입
    ("S6", "4150019003"),  # 공단본부삼거리 진입
    ("S7", "4150035903"),  # 가음정사거리 진입
]
VER = "2026-11-11"
VALID_FROM = "2026-11-18T00:00:00+09:00"

d = json.load(open(sys.argv[1], encoding="utf-8"))
nodes = d["nodes"]
links = [l for l in d["links"] if l["ROAD_NAME"] == ROAD]
out = {}
for l in links:
    out.setdefault(l["F_NODE"], []).append(l)


def nn(nid: str) -> str:
    n = nodes.get(nid)
    return n["NODE_NAME"] if n else ""


# 정방향 집합 (forward_set.py와 같은 방법)
inn = {}
for l in links:
    inn.setdefault(l["T_NODE"], []).append(l)
reach, st = {START}, [START]
while st:
    n = st.pop()
    if n in ENDS:
        continue
    for l in out.get(n, []):
        if l["T_NODE"] not in reach:
            reach.add(l["T_NODE"])
            st.append(l["T_NODE"])
co, st = set(ENDS), list(ENDS)
while st:
    n = st.pop()
    for l in inn.get(n, []):
        if l["F_NODE"] not in co and l["F_NODE"] not in ENDS:
            co.add(l["F_NODE"])
            st.append(l["F_NODE"])
fwd = {l["LINK_ID"]: l for l in links
       if l["F_NODE"] in reach and l["T_NODE"] in co and l["F_NODE"] not in ENDS}
fout = {}
for l in fwd.values():
    fout.setdefault(l["F_NODE"], []).append(l)

# 본선 경로
main, node = [], START
while node not in ENDS:
    cand = fout[node]
    if len(cand) > 1:
        cand = [c for c in cand if c["ROAD_TYPE"] == "002"]
        assert len(cand) == 1, node
    main.append(cand[0])
    node = cand[0]["T_NODE"]
main_nodes = [START] + [l["T_NODE"] for l in main]
main_ids = {l["LINK_ID"] for l in main}

# 측도 가지: 분기 노드의 비본선 링크를 따라 본선 노드(또는 끝)에 닿을 때까지
side = {}  # 분기 노드 -> 링크 목록
for n, cand in fout.items():
    for c in cand:
        if c["LINK_ID"] in main_ids:
            continue
        chain, cur = [c], c
        while cur["T_NODE"] not in main_nodes and cur["T_NODE"] not in ENDS:
            nxt = fout[cur["T_NODE"]]
            assert len(nxt) == 1
            cur = nxt[0]
            chain.append(cur)
        side[n] = chain
_covered = main_ids | {s["LINK_ID"] for v in side.values() for s in v}
assert _covered == set(fwd), (len(main_ids), {k: [s["LINK_ID"] for s in v] for k, v in side.items()},
                              set(fwd) - _covered, _covered - set(fwd))

# 구간 배정
bstart = {nid: sid for sid, nid in BOUNDARIES}
rows, seg, seqs = [], None, {}


def add(l, sid, mainline, note):
    seqs[sid] = seqs.get(sid, 0) + 1
    rows.append({
        "segment_id": sid, "seq": seqs[sid], "link_id": l["LINK_ID"], "source": "its",
        "link_length_m": f'{float(l["LENGTH"]):.1f}', "is_mainline": mainline,
        "nodelink_ver": VER, "valid_from": VALID_FROM,
        "f_node_name": nn(l["F_NODE"]), "t_node_name": nn(l["T_NODE"]),
        "road_type": l["ROAD_TYPE"], "max_speed": l["MAX_SPD"], "lanes": l["LANES"],
        "note": note,
    })


i = 0
while i < len(main):
    l = main[i]
    if l["F_NODE"] in bstart:
        seg = bstart[l["F_NODE"]]
    if l["F_NODE"] in side:
        # 분기: 본선 블록을 먼저, 이어서 측도 블록
        sc = side[l["F_NODE"]]
        rejoin = sc[-1]["T_NODE"]
        block = []
        while True:
            block.append(main[i])
            if main[i]["T_NODE"] == rejoin or main[i]["T_NODE"] in ENDS and rejoin in ENDS:
                break
            i += 1
        names = nn(l["F_NODE"]) + "→" + nn(block[-1]["T_NODE"])
        for b in block:
            add(b, seg, 1, f"지하차도 본선({names}) F={b['F_NODE']} T={b['T_NODE']}")
        for s in sc:
            add(s, seg, 0, f"지상 측도({nn(sc[0]['F_NODE'])}→{nn(sc[-1]['T_NODE'])}) "
                           f"F={s['F_NODE']} T={s['T_NODE']}")
    else:
        add(l, seg, 1, f"F={l['F_NODE']} T={l['T_NODE']}")
    i += 1

with open(sys.argv[2], "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

# 요약
print("forward links", len(fwd), "rows", len(rows))
for sid, _ in BOUNDARIES:
    r = [x for x in rows if x["segment_id"] == sid]
    m = [x for x in r if x["is_mainline"] == 1]
    s = [x for x in r if x["is_mainline"] == 0]
    print(sid, "links", len(r), "main", len(m), f"main_len={sum(float(x['link_length_m']) for x in m):.1f}",
          "side", len(s), f"side_len={sum(float(x['link_length_m']) for x in s):.1f}")
print("== 링크 속성 분포(정방향)")
for k in ("ROAD_RANK", "ROAD_USE", "MULTI_LINK", "CONNECT", "UPDATEDATE", "HIST_TYPE", "C-ITS", "REST_VEH"):
    vals = {}
    for l in fwd.values():
        vals[l[k]] = vals.get(l[k], 0) + 1
    print(k, vals)
print("== 노드 유형")
for n in sorted({x for l in fwd.values() for x in (l["F_NODE"], l["T_NODE"])}):
    nd = nodes[n]
    print(n, nd["NODE_NAME"], nd["NODE_TYPE"], nd["TURN_P"], [round(v, 1) for v in nd["_xy"]])
print("multilink matches", len(d["multilink_ids"]))
print("LENGTH vs geom max diff",
      max(abs(float(l["LENGTH"]) - l["_geom_len"]) for l in fwd.values()))
