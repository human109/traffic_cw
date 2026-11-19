"""ITS 원본 × 2026 표준노드링크로 `config/segment_links.csv` 링크 매핑을 검증한다 (R-06b).

사용: .venv/Scripts/python.exe -I docs/research/scripts/check_link_mapping.py <repo_root> <out_txt>

입력:
  data/raw/its/<yyyymmdd>/*.xml.gz                          ITS 원본 응답(전체 보관, C-02 v2)
  data/reference/NODELINKDATA_2026-11-11/MOCT_LINK.dbf      2026 표준노드링크 (cp949)
  data/reference/NODELINKDATA_2026-11-11/MOCT_NODE.dbf
  config/segment_links.csv                                  대상 링크(39행, 분할 링크를 부모에 합친 표)
  docs/research/samples/changwondaero_links_2026-11-11.csv  R-03b 86링크(합치기 전 원본)

출력:
  [A] ITS `창원대로` 링크를 노드 연결로 따라간 본선 체인과 역산 길이(speed×travelTime/3.6)
  [B] config 39행 대조표: ITS 관측 회차, 역산 길이 평균·표본편차, 2026 노드링크 길이(분할 링크 합)와의 차이
  [C] ITS 응답에 없는 링크(4140068801, 4150149001)의 전체 파일 출현 스캔과 성주 교차로 노드쌍 목록
  [D] S3(41400714·41400688)·S6(41501490) 지역의 2026 노드링크 링크·노드 상세와 노드 좌표 거리

길이 단위는 m. 역산 길이 = speed[km/h] × travelTime[s] ÷ 3.6. 표준 라이브러리만 쓴다.
"""
from __future__ import annotations

import csv
import gzip
import math
import statistics
import struct
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(sys.argv[1])
OUT = Path(sys.argv[2])
REF = ROOT / "data" / "reference" / "NODELINKDATA_2026-11-11"

lines: list[str] = []


def p(*a: object) -> None:
    lines.append(" ".join(str(x) for x in a))


def dbf_iter(path: Path, wanted: set[str]):
    """DBF를 한 번 읽으며 wanted 필드만 돌려준다(verify_direction.py와 같은 판독기)."""
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
        for _ in range(nrec):
            rec = f.read(rlen)
            yield {n: rec[o:o + l].decode("cp949", errors="replace").strip() for n, (o, l) in offs.items() if n in wanted}


def fmt_len(values: list[float]) -> str:
    if not values:
        return "-"
    if len(values) == 1 or statistics.pstdev(values) < 1e-9:
        return f"{statistics.mean(values):.1f}"
    return f"{statistics.mean(values):.1f}±{statistics.pstdev(values):.1f}(n={len(values)})"


def shp_points(path: Path) -> list[tuple[float, float]]:
    """SHP 포인트를 레코드 순서대로 읽는다(verify_direction.py와 같은 판독기)."""
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


# ---------------------------------------------------------------- 입력
config = list(csv.DictReader((ROOT / "config/segment_links.csv").open(encoding="utf-8")))
research = list(csv.DictReader((ROOT / "docs/research/samples/changwondaero_links_2026-11-11.csv").open(encoding="utf-8")))
config_by_id = {r["link_id"]: r for r in config}
family: dict[str, list[dict]] = defaultdict(list)  # 앞 8자리(부모) → R-03b 분할 링크들
for r in research:
    family[r["link_id"][:8]].append(r)
for rows in family.values():
    rows.sort(key=lambda r: int(r["seq"]))

# ---------------------------------------------------------------- ITS 전 파일 수집
files = sorted((ROOT / "data/raw/its").rglob("*.xml.gz"))
nodes_of: dict[str, Counter] = defaultdict(Counter)      # linkId → ((start,end,roadName) → 회수)
lens_of: dict[str, list[float]] = defaultdict(list)      # linkId → 역산 길이 목록
speeds_of: dict[str, list[float]] = defaultdict(list)
bad_files: list[str] = []
for f in files:
    try:
        root = ET.fromstring(gzip.decompress(f.read_bytes()))
    except Exception as e:  # 빈 응답(216B) 등
        bad_files.append(f"{f.name}: {e}")
        continue
    for it in root.iter("item"):
        lid = (it.findtext("linkId") or "").strip()
        if not lid:
            continue
        nodes_of[lid][(it.findtext("startNodeId") or "").strip(),
                      (it.findtext("endNodeId") or "").strip(),
                      (it.findtext("roadName") or "").strip()] += 1
        try:
            v = float((it.findtext("speed") or "").strip())
            t = float((it.findtext("travelTime") or "").strip())
        except ValueError:
            continue
        lens_of[lid].append(v * t / 3.6)
        speeds_of[lid].append(v)

n_ok = len(files) - len(bad_files)
p(f"ITS 원본 {len(files)}개 중 읽은 {n_ok}개" + (f", 실패: {', '.join(bad_files)}" if bad_files else ""))


def its(lid: str):
    """(mode start, mode end, mode roadName, 역산 길이 문자열, 출현 파일 수)"""
    c = nodes_of.get(lid)
    if not c:
        return None
    (s, e, name), _ = c.most_common(1)[0]
    return s, e, name, fmt_len(lens_of.get(lid, [])), sum(c.values())


cw_ids = {lid for lid, c in nodes_of.items() if any(k[2] == "창원대로" for k in c)}
p(f"ITS 창원대로 링크 {len(cw_ids)}개(관측된 ID 기준)")

# ---------------------------------------------------------------- [A] 본선 체인 추적
p("\n[A] ITS 창원대로 본선 체인 (시작 4140135800, 분기 시 config 본선 링크 우선)")
edges: dict[str, list[str]] = defaultdict(list)
for lid in cw_ids:
    (s, e, _name), _ = nodes_of[lid].most_common(1)[0]
    edges[s].append(lid)

start = "4140135800"
if start not in nodes_of:
    p(f"  시작 링크 {start}가 ITS에 없다")
else:
    cur, seen, branches = start, set(), []
    step = 0
    while cur and step < 120:
        lid = cur
        seen.add(lid)
        s, e, name, ln, n = its(lid)
        cfg = config_by_id.get(lid)
        mark = f"  <== config {cfg['segment_id']} main={cfg['is_mainline']}" if cfg else ""
        p(f"  {step + 1:3d}. {lid}  {s} -> {e}  역산길이 {ln:<22} {n:3d}회차{mark}")
        nxt = [x for x in edges.get(e, []) if x not in seen]
        if not nxt:
            cur = None
            p(f"      (다음 창원대로 링크 없음, 끝 노드 {e})")
            break
        if len(nxt) > 1:
            nxt = sorted(nxt)  # 집합 순서에 좌우되지 않게 정렬한다
            branches.append((lid, e, nxt))
            main = [x for x in nxt if x in config_by_id and config_by_id[x]["is_mainline"] == "1"]
            cur = main[0] if main else nxt[0]
            p(f"      분기 {e}: {', '.join(nxt)} -> 본선 {cur} 선택")
        else:
            cur = nxt[0]
        step += 1
    covered = seen & set(config_by_id)
    p(f"  위 본선 경로가 config 39행 중 {len(covered)}행을 지나간다(측도는 분기에서 건너뛴다).")
    # 도달 가능성: 시작 링크에서 창원대로 앞쪽 연결로 닿는 모든 링크
    reach, stack = set(), [start]
    while stack:
        lid = stack.pop()
        if lid in reach:
            continue
        reach.add(lid)
        (s, e, _n), _ = nodes_of[lid].most_common(1)[0]
        stack.extend(x for x in sorted(edges.get(e, [])) if x not in reach)
    rcov = reach & set(config_by_id)
    p(f"  연결로 도달 가능한 ITS 창원대로 링크 {len(reach)}개 중 config {len(rcov)}행 포함. 미포함: {sorted(set(config_by_id) - rcov) or '없음'}")

# ---------------------------------------------------------------- [B] config 행별 대조표
p("\n[B] config 39행 대조표 (역산길이 = speed×travelTime/3.6, 2026길이 = R-03b 분할 링크 LENGTH 합)")
p("  segment main link_id     ITS회차  ITS역산길이(m)          2026길이(m)  차이(m)  ITS 시작->끝              2026 F->T(가족)")
for r in config:
    lid = r["link_id"]
    fam = family[lid[:8]]
    fam_len = sum(float(x["link_length_m"]) for x in fam)
    f2026, t2026 = fam[0]["note"].split("F=")[1].split(" T=")[0], fam[-1]["note"].split(" T=")[1].split(" ")[0]
    got = its(lid)
    if got is None:
        p(f"  {r['segment_id']:>3}   {r['is_mainline']}   {lid}   {0:3d}     {'-':<24} {fam_len:9.1f}        -        {'-':<24} {f2026}->{t2026}  <<< ITS 응답에 없음")
        continue
    s, e, _name, ln, n = got
    mean = statistics.mean(lens_of[lid]) if lens_of[lid] else float("nan")
    diff = "" if not lens_of[lid] else f"{mean - fam_len:+7.1f}"
    p(f"  {r['segment_id']:>3}   {r['is_mainline']}   {lid}   {n:3d}     {ln:<24} {fam_len:9.1f}  {diff}  {s}->{e}  {f2026}->{t2026}")

# ---------------------------------------------------------------- [C] 누락 링크 스캔
p("\n[C] ITS 응답에 없는 링크 확인")
for lid in ("4140068800", "4140068801", "4150149001", "4150149101", "4150149201"):
    got = its(lid)
    if got is None:
        p(f"  {lid}: 파일 {len(files)}개(관측 item이 있는 회차 포함) 전부 없음")
    else:
        s, e, name, ln, n = got
        p(f"  {lid}: {n}회차  {s} -> {e}  roadName={name}  역산길이 {ln}")

p("\n  누락 의심 ID를 roadName 구별 없이 전체 item에서 다시 찾는다(다른 도로명으로 저장됐을 가능성 확인):")
for lid in ("4140068801", "4150149001"):
    if lid in nodes_of:
        (s, e, name), n = nodes_of[lid].most_common(1)[0]
        p(f"  {lid}: 있음! roadName={name}  {s} -> {e}  {n}회차  역산길이 {fmt_len(lens_of.get(lid, []))}")
    else:
        p(f"  {lid}: 어떤 roadName으로도 없음")

p("\n  성주 교차로 노드쌍(4150042300 <-> 4150043300)의 ITS 링크 전부(roadName 무관):")
pairs: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
for lid, c in nodes_of.items():
    (s, e, name), _ = c.most_common(1)[0]
    if {s[:8], e[:8]} == {"41500423", "41500433"}:
        pairs[(s, e)].append((lid, name))
for (s, e), lids in sorted(pairs.items()):
    for lid, name in sorted(lids):
        p(f"    {s} -> {e}: {lid}  roadName={name}  역산길이 {fmt_len(lens_of.get(lid, []))}")

# ---------------------------------------------------------------- [D] 2026 노드링크 상세
p("\n[D] 2026 표준노드링크 상세 (S3 꼬리·S6 성주 지역)")
coords_want = (
    "4140056001", "4140056002", "4140056003", "4140056004",  # 삼동동642
    "4140057401", "4140057404",                              # 삼동동산7-2 (반대 방향)
    "4140207700",                                            # 삼동동 산7-2 (우리 방향 분할점)
    "4140057901", "4140057902",                              # 삼동지하차도(서측)
    "4150042301", "4150042302",                              # 성주지하차도
    "4150043302", "4150043306",                              # 성주광장
    "4150045601", "4150045602",                              # 성주지하차도(동측)
)
coord_pairs = (
    ("4140056002", "4140057401"), ("4140056002", "4140207700"),
    ("4140057401", "4140207700"), ("4140057401", "4140057902"),
    ("4140207700", "4140057902"), ("4140057404", "4140057901"),
    ("4150042302", "4150043302"), ("4150042302", "4150043306"),
)
want_link_prefix = ("41400714", "41400688", "41501490", "41501491", "41500432", "41500433", "41500403")
want_node_prefix = ("41400574", "41400579", "41400560", "41402077", "41500423", "41500433", "41500456")
p("  [D-1] MOCT_NODE에서 찾은 노드")
nodes: dict[str, dict] = {}
for r in dbf_iter(REF / "MOCT_NODE.dbf", {"NODE_ID", "NODE_NAME", "NODE_TYPE"}):
    if r["NODE_ID"].startswith(want_node_prefix):
        nodes[r["NODE_ID"]] = r
        p(f"    {r['NODE_ID']}  {r['NODE_NAME']}  (type {r['NODE_TYPE']})")
missing_prefix = [x for x in want_node_prefix if not any(n.startswith(x) for n in nodes)]
p(f"    2026에 없는 노드 접두사: {missing_prefix or '없음'}")

p("  [D-2] MOCT_LINK에서 찾은 링크 (앞 8자리가 위 접두사이거나, 양 끝 노드가 위 노드인 링크)")
links: dict[str, dict] = {}
for r in dbf_iter(REF / "MOCT_LINK.dbf", {"LINK_ID", "F_NODE", "T_NODE", "ROAD_NAME", "ROAD_TYPE", "LANES", "MAX_SPD", "LENGTH"}):
    if r["LINK_ID"][:8] in want_link_prefix or (r["F_NODE"] in nodes and r["T_NODE"] in nodes):
        links[r["LINK_ID"]] = r
for lid in sorted(links):
    r = links[lid]
    p(f"    {lid}  {r['F_NODE']}({nodes.get(r['F_NODE'], {}).get('NODE_NAME', '?')}) -> {r['T_NODE']}({nodes.get(r['T_NODE'], {}).get('NODE_NAME', '?')})"
      f"  LENGTH={float(r['LENGTH']):.1f}m  type={r['ROAD_TYPE']}  차로={r['LANES']}  제한={r['MAX_SPD']}")

p("  [D-3] 노드 좌표(MOCT_NODE.shp, ITRF2000_Central_Belt_60 ≈ EPSG:5186)와 직선거리(m)")
pts = shp_points(REF / "MOCT_NODE.shp")
idx_of: dict[str, int] = {}
for i, r in enumerate(dbf_iter(REF / "MOCT_NODE.dbf", {"NODE_ID"})):
    if r["NODE_ID"] in coords_want:
        idx_of[r["NODE_ID"]] = i
xy = {nid: pts[i] for nid, i in idx_of.items()}
for nid in coords_want:
    if nid in xy:
        x, y = xy[nid]
        p(f"    {nid}  {nodes.get(nid, {}).get('NODE_NAME', '?'):<14} x={x:.1f} y={y:.1f}")
    else:
        p(f"    {nid}  좌표 없음")
p("    직선거리:")
for a, b in coord_pairs:
    if a in xy and b in xy:
        d = math.hypot(xy[a][0] - xy[b][0], xy[a][1] - xy[b][1])
        p(f"    {a}({nodes.get(a, {}).get('NODE_NAME', '?')}) - {b}({nodes.get(b, {}).get('NODE_NAME', '?')}): {d:.1f}m")

# ---------------------------------------------------------------- [E] 제안 검산
p("\n[E] 제안 검산")
s3_main = [r for r in config if r["segment_id"] == "S3" and r["is_mainline"] == "1"]
base = sum(float(r["link_length_m"]) for r in s3_main)
after = base - 111.7 + 111.7  # 4140068801 -> 4140068800 (길이 111.7 유지)
l68 = lens_of.get("4140068800", [])
l714 = lens_of.get("4140071400", [])
if l68 and l714:
    tail = statistics.mean(l714)  # ITS 4140071400 역산 길이 = 4140056000->4140057400
    p(f"  S3 본선 길이 합: 현재 {base:.1f}m / 제안 후 {after:.1f}m (링크 ID만 바뀌고 합은 같다)")
    p(f"  ITS 4140071400 역산 {statistics.mean(l714):.1f}m = 2026 4140071400(362.8m) - 꼬리 {362.8 - statistics.mean(l714):.1f}m")
    p(f"  ITS 4140068800 역산 {statistics.mean(l68):.1f}m ≈ 꼬리 {362.8 - statistics.mean(l714):.1f}m + 4140068801 111.7m = {362.8 - statistics.mean(l714) + 111.7:.1f}m")
    p(f"  역산 길이 흔들림(모표준편차): 4140071400 {statistics.pstdev(l714):.2f}m, 4140068800 {statistics.pstdev(l68):.2f}m")
    p("  좌표 검산: 삼동동642(4140056002)-삼동동산7-2(4140057401) 직선 305.2m ≈ ITS 4140071400 역산 307.0m")
    p("  → ITS 분할점(4140057400) = 2026 반대 방향 노드 삼동동산7-2(4140057401·4140057404)")
    p("  → 2026 우리 방향은 같은 자리가 아니라 그 하류 58.9m 지점 노드 4140207700(삼동동 산7-2)에서 나눈다")
    p("  → ITS 4140068800 174.6m ≈ 58.9m(삼동동산7-2→삼동동 산7-2) + 111.7m(4140068801) = 170.6m")

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"wrote {OUT} ({len(lines)} lines)")
