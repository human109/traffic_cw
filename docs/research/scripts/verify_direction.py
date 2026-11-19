"""창원대로 링크 방향 검증 (표준 라이브러리만).

사용: python -I verify_direction.py <repo_root> <out_txt>
검증:
 A. 노드 연결: research CSV(86링크, 상류→하류)에서 본선 링크끼리 T_NODE → 다음 본선 F_NODE가 이어지는지
 B. 좌표 진행: 각 링크의 F→T 벡터를 전체 축(첫 F 노드 → 마지막 T 노드)에 투영한 값이 양수인지
 C. 반대 방향 링크: 같은 두 노드를 T→F로 잇는 링크가 따로 있는지(양방향 도로에서 한쪽을 고른 것인지)
 D. ITS 대조: ITS 원본 응답의 startNodeId/endNodeId가 표준노드링크 F/T와 같은지
"""
from __future__ import annotations

import csv
import gzip
import math
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(sys.argv[1])
OUT = Path(sys.argv[2])
REF = ROOT / "data" / "reference" / "NODELINKDATA_2026-11-11"
lines: list[str] = []


def p(*a) -> None:
    lines.append(" ".join(str(x) for x in a))


def dbf_iter(path: Path, wanted: set[str]):
    with path.open("rb") as f:
        head = f.read(32)
        nrec, hlen, rlen = struct.unpack("<IHH", head[4:12])
        fields = []
        while True:
            d = f.read(32)
            if d[0] == 0x0D:
                break
            fields.append((d[:11].split(b"\x00")[0].decode("ascii"), d[16]))
        f.seek(hlen)
        offs, pos = {}, 1
        for name, flen in fields:
            offs[name] = (pos, flen)
            pos += flen
        for i in range(nrec):
            rec = f.read(rlen)
            yield i, {n: rec[o:o + l].decode("cp949", errors="replace").strip() for n, (o, l) in offs.items() if n in wanted}


def shp_points(path: Path) -> list[tuple[float, float]]:
    pts = []
    with path.open("rb") as f:
        f.seek(100)
        while True:
            h = f.read(8)
            if len(h) < 8:
                break
            clen = struct.unpack(">i", h[4:8])[0] * 2
            body = f.read(clen)
            stype = struct.unpack("<i", body[:4])[0]
            pts.append(struct.unpack("<dd", body[4:20]) if stype == 1 else (math.nan, math.nan))
    return pts


# --- 대상 링크
research = list(csv.DictReader((ROOT / "docs/research/samples/changwondaero_links_2026-11-11.csv").open(encoding="utf-8")))
config = list(csv.DictReader((ROOT / "config/segment_links.csv").open(encoding="utf-8")))
ids = {r["link_id"] for r in research}

# --- LINK.dbf: 대상 링크 + 대상 노드 사이의 모든 링크(반대 방향 탐색용)
links: dict[str, dict] = {}
pair_index: dict[tuple[str, str], list[str]] = {}
for _, r in dbf_iter(REF / "MOCT_LINK.dbf", {"LINK_ID", "F_NODE", "T_NODE", "ROAD_NAME", "LANES", "MAX_SPD", "ROAD_TYPE", "LENGTH"}):
    pair_index.setdefault((r["F_NODE"], r["T_NODE"]), []).append(r["LINK_ID"])
    if r["LINK_ID"] in ids:
        links[r["LINK_ID"]] = r
p(f"LINK.dbf에서 찾은 대상 링크: {len(links)}/{len(ids)}")

# --- NODE.dbf + NODE.shp 좌표
need_nodes = {links[i][k] for i in links for k in ("F_NODE", "T_NODE")}
pts = shp_points(REF / "MOCT_NODE.shp")
nodes: dict[str, dict] = {}
for idx, r in dbf_iter(REF / "MOCT_NODE.dbf", {"NODE_ID", "NODE_NAME"}):
    if r["NODE_ID"] in need_nodes:
        nodes[r["NODE_ID"]] = {"name": r["NODE_NAME"], "xy": pts[idx]}
p(f"좌표를 찾은 노드: {len(nodes)}/{len(need_nodes)}")

# --- A. 본선 체인 연결
p("\n[A] 본선 노드 연결 (CSV 순서, is_mainline=1)")
main = [r for r in research if r["is_mainline"] == "1"]
breaks = 0
for a, b in zip(main, main[1:]):
    ta, fb = links[a["link_id"]]["T_NODE"], links[b["link_id"]]["F_NODE"]
    if ta != fb:
        breaks += 1
        p(f"  끊김: {a['link_id']}(T={ta} {nodes.get(ta, {}).get('name')}) → {b['link_id']}(F={fb} {nodes.get(fb, {}).get('name')})")
p(f"  본선 {len(main)}개, 끊김 {breaks}건")

side = [r for r in research if r["is_mainline"] == "0"]
main_nodes = {links[r["link_id"]][k] for r in main for k in ("F_NODE", "T_NODE")}
p(f"  측도 {len(side)}개: 측도 묶음의 시작·끝이 본선 노드에 닿는지 아래 B·C로 함께 확인")

# --- B. 좌표 진행
first = nodes[links[research[0]["link_id"]]["F_NODE"]]["xy"]
last = nodes[links[research[-1]["link_id"]]["T_NODE"]]["xy"]
ax, ay = last[0] - first[0], last[1] - first[1]
norm = math.hypot(ax, ay)
ux, uy = ax / norm, ay / norm
p(f"\n[B] 전체 축: 시작 {nodes[links[research[0]['link_id']]['F_NODE']]['name']} → 끝 {nodes[links[research[-1]['link_id']]['T_NODE']]['name']}"
  f", 직선거리 {norm:.0f}m, 방위각 {math.degrees(math.atan2(ax, ay)) % 360:.0f}°(북=0, 동=90)")
neg = 0
for r in research:
    L = links[r["link_id"]]
    f, t = nodes[L["F_NODE"]]["xy"], nodes[L["T_NODE"]]["xy"]
    proj = (t[0] - f[0]) * ux + (t[1] - f[1]) * uy
    straight = math.hypot(t[0] - f[0], t[1] - f[1])
    if proj <= 0 and straight > 1:
        neg += 1
        p(f"  역방향 의심: {r['segment_id']} {r['link_id']} 투영 {proj:.1f}m / 직선 {straight:.1f}m")
p(f"  투영이 0 이하인 링크(직선 1m 초과): {neg}건 / {len(research)}")

# 상류→하류 누적 위치가 단조 증가하는지 (본선 F 노드 기준)
pos = [((nodes[links[r['link_id']]['F_NODE']]['xy'][0] - first[0]) * ux + (nodes[links[r['link_id']]['F_NODE']]['xy'][1] - first[1]) * uy) for r in main]
dec = [(main[i]["link_id"], round(pos[i - 1] - pos[i], 1)) for i in range(1, len(pos)) if pos[i] < pos[i - 1] - 1]
p(f"  본선 시작 노드 위치가 뒤로 가는 곳(1m 초과): {dec or '없음'}")

# --- C. 반대 방향 링크
p("\n[C] 같은 두 노드를 반대로 잇는 링크")
has_rev = 0
for r in research:
    L = links[r["link_id"]]
    rev = pair_index.get((L["T_NODE"], L["F_NODE"]), [])
    if rev:
        has_rev += 1
p(f"  반대 방향 링크가 있는 대상 링크: {has_rev}/{len(research)} (교차로가 방향별로 분리된 구간은 반대 링크가 다른 노드쌍일 수 있음)")

# --- D. ITS 대조
raw_files = sorted((ROOT / "data" / "raw" / "its").rglob("*.xml.gz"))
p(f"\n[D] ITS 원본 대조: {raw_files[-1].name if raw_files else '없음'}")
if raw_files:
    root = ET.fromstring(gzip.decompress(raw_files[-1].read_bytes()))
    its = {}
    for it in root.iter("item"):
        lid = (it.findtext("linkId") or "").strip()
        its[lid] = {k: (it.findtext(k) or "").strip() for k in ("startNodeId", "endNodeId", "roadName", "roadDrcType", "speed")}
    # ITS는 교차로 중심 노드(끝 00), 2026 노드링크는 방향별 노드(끝 02/03 …) → 앞 8자리(교차로 단위)로 비교
    def k8(n: str) -> str:
        return n[:8]

    ok = mism = rev_cnt = 0
    for r in config:
        lid = r["link_id"]
        if lid not in its:
            p(f"  ITS 응답에 없음: {r['segment_id']} {lid}")
            continue
        L = links[lid]
        s, e = its[lid]["startNodeId"], its[lid]["endNodeId"]
        family = [c for c in links if c[:8] == lid[:8] and links[c]["F_NODE"] and c in {x["link_id"] for x in research if x["segment_id"] or True}]
        f_set = {k8(links[c]["F_NODE"]) for c in family}
        t_set = {k8(links[c]["T_NODE"]) for c in family}
        start_ok = k8(s) in f_set
        end_ok = k8(e) in t_set
        reversed_ = k8(s) in t_set and k8(e) in f_set and not (start_ok and end_ok)
        rev_cnt += reversed_
        if start_ok and end_ok:
            ok += 1
        else:
            mism += 1
            p(f"  불일치: {r['segment_id']} {lid} ITS {s}→{e} / 노드링크(분할 포함) F{sorted(f_set)} T{sorted(t_set)} 역방향={reversed_}")
    p(f"  ITS 시작·끝 교차로(노드 앞 8자리) 일치: {ok}, 불일치: {mism}, 역방향: {rev_cnt}")
    p(f"  roadName 값: {sorted({its[r['link_id']]['roadName'] for r in config if r['link_id'] in its})}")
    p(f"  roadDrcType 값: {sorted({its[r['link_id']]['roadDrcType'] for r in config if r['link_id'] in its})}")

    # 반대 방향 링크의 ITS 속도(참고)
    p("\n[참고] 같은 구간 반대 방향 링크의 ITS 속도 (출근 시간대 방향별 차이)")
    # ITS 응답 안에서 시작·끝 교차로가 뒤바뀐 링크 = 반대 방향
    by_pair: dict[tuple[str, str], list[str]] = {}
    for lid, v in its.items():
        by_pair.setdefault((k8(v["startNodeId"]), k8(v["endNodeId"])), []).append(lid)
    found = 0
    for r in config:
        lid = r["link_id"]
        if lid not in its:
            continue
        s, e = k8(its[lid]["startNodeId"]), k8(its[lid]["endNodeId"])
        opp = [x for x in by_pair.get((e, s), []) if x != lid]
        if opp:
            found += 1
            o = opp[0]
            p(f"  {r['segment_id']} main={r['is_mainline']} 우리 {lid} {its[lid]['speed']:>5} km/h | 반대 {o} {its[o]['speed']:>5} km/h ({its[o]['roadName']})")
        else:
            p(f"  {r['segment_id']} main={r['is_mainline']} 우리 {lid} {its[lid]['speed']:>5} km/h | 반대 방향 링크 없음(같은 교차로 쌍)")
    p(f"  반대 방향 링크를 찾은 대상: {found}")

OUT.write_text("\n".join(lines), encoding="utf-8")
