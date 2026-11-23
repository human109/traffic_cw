"""R-09: 원이대로(명곡교→가음정사거리, 출근 방향) 링크 대응·구간 후보·방향 속도·응답 빈도 분석.

사용: python -I analyze_wonidaero.py <원이대로 JSON> <its_wonidaero_raw_items.csv> <출력 텍스트>
표준 라이브러리만 사용한다. 원본 파일은 읽기만 한다.

- ours = 명곡교→가음정사거리 진행 방향(남동→남서, ITS 링크 31개)
- opp  = 반대 방향(ITS 링크 31개, 같은 노드쌍의 짝)
- ITS 역산 길이 = speed × travelTime ÷ 3.6 (회차 평균)
- 2026 대응 길이 = MOCT_LINK.LENGTH (배포본 2026-11-11), 본 스크립트에 하드코딩한 값은
  dump_road_links_named.py 출력에서 옮긴 것이다.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------- 상수
# ours(진행 방향) ITS 링크, 상류→하류 순서. 괄호 안은 구간 후보 경계 후보가 끝나는 링크 표시용.
OURS = [
    "4140114500", "4140112700", "4140111300", "4140109100", "4140104000",
    "4140102800", "4150146700", "4150145900", "4150145100", "4150144300",
    "4150143500", "4150142600", "4150141700", "4150140900", "4150140300",
    "4150139500",  # -- 창원광장 로터리(ITS 원이대로 item 없음) --
    "4150136700", "4150134900", "4150131300", "4150128600", "4150120100",
    "4150102800", "4150090800", "4150086400", "4150081200", "4150076500",
    "4150071300", "4150069300", "4150061200", "4150056300", "4150054500",
]
# 반대 방향 = ours 링크 ID − 100 (31쌍 전부 성립, walk_its_paths.py로 확인)
OPP = [str(int(x) - 100) for x in OURS]
# 구간 후보 (Option A, 5구간 + 참고 W0). (구간, [ITS 링크...], 마지막 ITS 노드명)
SEGMENTS = [
    ("W0(참고)", ["4140126100", "4140123500", "4140117300", "4140115100"], "명곡교(서측)", "목련삼거리→명곡교"),
    ("W1", ["4140114500", "4140112700", "4140111300", "4140109100", "4140104000",
            "4140102800", "4150146700", "4150145900"], "중앙중사거리", "명곡교→중앙중사거리"),
    ("W2", ["4150145100", "4150144300", "4150143500"], "용지사거리", "중앙중사거리→용지사거리"),
    ("W3", ["4150142600", "4150141700", "4150140900", "4150140300", "4150139500",
            "4150136700"], "한국은행사거리", "용지사거리→한국은행사거리(창원광장 로터리 포함)"),
    ("W4", ["4150134900", "4150131300", "4150128600", "4150120100",
            "4150102800"], "성원아파트사거리", "한국은행사거리→성원아파트사거리"),
    ("W5", ["4150090800", "4150086400", "4150081200", "4150076500",
            "4150071300", "4150069300", "4150061200", "4150056300", "4150054500"],
     "가음정사거리", "성원아파트사거리→가음정사거리"),
]
# 2026 배포본(2026-11-11) 링크 길이(m). dump_road_links_named.py 출력에서 옮김.
L2026 = {
    "4140114500": 41.1, "4140112700": 202.0, "4140111301": 11.8,
    "4140109100": 152.3, "4140109101": 10.1, "4140104000": 299.4,
    "4140104001": 24.0, "4140102800": 56.7, "4150146700": 72.2,
    "4150146701": 13.3, "4150145900": 320.0, "4150145901": 12.3,
    "4150145902": 317.1, "4150145100": 264.0, "4150145101": 11.7,
    "4150145102": 264.0, "4150144300": 257.8, "4150144301": 11.4,
    "4150144302": 257.8, "4150143500": 425.3, "4150143501": 12.0,
    "4150142600": 458.6, "4150141701": 11.9, "4150140900": 131.2,
    "4150140901": 11.9,
    "4150140300": 177.0, "4150140301": 11.8, "4150139500": 98.3,
    "4150136700": 87.4, "4150136702": 11.8, "4150134900": 188.4,
    "4150134901": 12.0, "4150131300": 183.7, "4150131301": 12.1,
    "4150128600": 122.3, "4150128601": 20.2, "4150120100": 325.2,
    "4150120101": 12.0, "4150102800": 422.3, "4150102801": 12.9,
    "4150090800": 243.5, "4150090801": 12.5, "4150086400": 138.9,
    "4150086401": 13.7, "4150081200": 220.4, "4150081201": 11.1,
    "4150076500": 231.9, "4150076501": 12.7, "4150071300": 139.0,
    "4150071301": 12.0, "4150069300": 46.2, "4150069301": 12.2,
    "4150061200": 189.0, "4150061201": 12.0, "4150056300": 115.1,
    "4150054500": 56.3, "4150054501": 10.6,
    # W0(참고) 동측
    "4140126100": 310.9, "4140123501": 12.5, "4140117300": 263.3,
    "4140117301": 11.9, "4140115100": 145.2,
}
# ITS 링크 → 2026 링크 목록(길이 배분 전 총합의 원천). 특수 3케이스 포함.
ITS_TO_2026 = {
    "4140114500": ["4140114500"],
    "4140112700": None,  # 4140112700+4140111300 합산 후 비례 배분
    "4140111300": None,
    "4140109100": ["4140109100", "4140109101"],
    "4140104000": ["4140104000", "4140104001"],
    "4140102800": ["4140102800"],
    "4150146700": ["4150146700", "4150146701"],
    "4150145900": ["4150145900", "4150145901", "4150145902"],
    "4150145100": ["4150145100", "4150145101", "4150145102"],
    "4150144300": ["4150144300", "4150144301", "4150144302"],
    "4150143500": ["4150143500", "4150143501"],
    "4150142500": None,  # (opp) 4150142500+4150141600 합산 후 비례 배분
    "4150141600": None,
    "4150142600": None,  # (ours) 4150142600+4150141700 합산 후 비례 배분 (2026 4150142600+4150141701)
    "4150141700": None,
    "4150140900": ["4150140900", "4150140901"],
    "4150140300": ["4150140300", "4150140301"],
    "4150139500": ["4150139500"],
    "4150136700": ["4150136700", "4150136702"],
    "4150134900": ["4150134900", "4150134901"],
    "4150131300": ["4150131300", "4150131301"],
    "4150128600": ["4150128600", "4150128601"],
    "4150120100": ["4150120100", "4150120101"],
    "4150102800": ["4150102800", "4150102801"],
    "4150090800": ["4150090800", "4150090801"],
    "4150086400": ["4150086400", "4150086401"],
    "4150081200": ["4150081200", "4150081201"],
    "4150076500": ["4150076500", "4150076501"],
    "4150071300": ["4150071300", "4150071301"],
    "4150069300": ["4150069300", "4150069301"],
    "4150061200": ["4150061200", "4150061201"],
    "4150056300": ["4150056300"],
    "4150054500": ["4150054500", "4150054501"],
    # W0(참고)
    "4140126100": None,  # 4140126100+4140123500 합산 후 비례 배분 (2026 4140126100+4140123501)
    "4140123500": None,
    "4140117300": ["4140117300", "4140117301"],
    "4140115100": ["4140115100"],
}
# 특수 배분(합산 후 비례): (ITS 링크 쌍, 2026 길이 총합)
PAIR_ALLOC = {
    ("4140112700", "4140111300"): L2026["4140112700"] + L2026["4140111301"],
    ("4150142600", "4150141700"): L2026["4150142600"] + L2026["4150141701"],
    ("4140126100", "4140123500"): L2026["4140126100"] + L2026["4140123501"],
}

# ---------------------------------------------------------------- 입력
nl = json.load(open(sys.argv[1], encoding="utf-8"))
nodes = nl["nodes"]
rows = list(csv.DictReader(open(sys.argv[2], encoding="utf-8")))


def nn(nid):
    n = nodes.get(nid)
    return n["NODE_NAME"] if n else "?"


out = open(sys.argv[3], "w", encoding="utf-8")
w = lambda s="": out.write(s + "\n")  # noqa: E731

# ---------------------------------------------------------------- 1. ITS 링크 요약
by_link = defaultdict(list)
for r in rows:
    by_link[r["link_id"]].append(r)

its_len = {}   # ITS 역산 길이 평균
its_sn, its_en = {}, {}
for lid, rs in by_link.items():
    lens = [float(r["speed"]) * float(r["travel_time"]) / 3.6
            for r in rs if r["speed"] and r["travel_time"]
            and float(r["speed"]) > 0 and float(r["travel_time"]) > 0]
    its_len[lid] = sum(lens) / len(lens) if lens else 0.0
    its_sn[lid], its_en[lid] = rs[0]["start_node"], rs[0]["end_node"]

w("== 1. ours(진행 방향) ITS 링크 31개 — ITS 역산 길이 vs 2026 배포본 길이")
w("ITS링크 | ITS 노드쌍(2026 노드명) | 역산(m) | 2026링크(합 m) | 차이(m)")
alloc = {}  # ITS 링크 → config 제안 길이
for pair, total in PAIR_ALLOC.items():
    s = sum(its_len[p] for p in pair)
    for p in pair:
        alloc[p] = total * its_len[p] / s
W0_LINKS = ["4140126100", "4140123500", "4140117300", "4140115100"]
for lid in OURS + W0_LINKS:
    src = ITS_TO_2026[lid]
    if src is None:
        pair = next(p for p in PAIR_ALLOC if lid in p)
        l26 = alloc[lid]
        src_s = "비례배분"
    else:
        l26 = sum(L2026[x] for x in src)
        src_s = "+".join(src)
    alloc[lid] = alloc.get(lid, l26)
    sn, en = its_sn[lid], its_en[lid]
    sn_name = nn(sn) if sn in nodes else "ITS전용노드"
    en_name = nn(en) if en in nodes else "ITS전용노드"
    w(f"{lid} | {sn}({sn_name}) → {en}({en_name}) "
      f"| {its_len[lid]:.1f} | {src_s} ({l26:.1f}) | {l26 - its_len[lid]:+.1f}")
w("")
w(f"2026 합(ours 스코프, 로터리 갭 제외): {sum(alloc[l] for l in OURS):.1f} m")
w(f"ITS 역산 합(같음): {sum(its_len[l] for l in OURS):.1f} m")

# ---------------------------------------------------------------- 2. 구간 후보
w("")
w("== 2. 구간 후보(Option A) — 길이는 config 제안값(2026 배분) 기준")
for seg, links, endname, desc in SEGMENTS:
    tot = sum(alloc.get(l, its_len.get(l, 0.0)) for l in links)
    w(f"{seg} {desc}: {len(links)}링크 {tot:.1f}m (끝={endname})")

# ---------------------------------------------------------------- 3. 응답 빈도(결측률)
w("")
w("== 3. 원본 응답 빈도 — 일별 회차 수와 ours 링크 수신 회차")
by_file = defaultdict(set)          # file → created_date 집합
file_day = {}
for r in rows:
    by_file[r["file"]].add(r["created_date"])
    file_day[r["file"]] = r["file"].split("/")[0]
day_files = defaultdict(set)
for f, ds in by_file.items():
    for _ in ds:
        day_files[file_day[f]].add(f)
day_dates = defaultdict(set)
for r in rows:
    day_dates[r["file"].split("/")[0]].add(r["created_date"])

link_days = defaultdict(lambda: defaultdict(set))  # day → link → {created_date}
for r in rows:
    if r["link_id"] in OURS + OPP:
        day = r["file"].split("/")[0]
        link_days[day][r["link_id"]].add(r["created_date"])

w("일자 | 파일 수 | 회차(createdDate) 수 | ours 링크 최소 수신 회차 | ours 결측률 | opp 최소 | opp 결측률")
for day in sorted(day_files):
    nf = len(day_files[day])
    nd = len(day_dates[day])
    omin = min(len(link_days[day].get(l, set())) for l in OURS)
    pmin = min(len(link_days[day].get(l, set())) for l in OPP)
    w(f"{day} | {nf} | {nd} | {omin}/{nd} | {1 - omin / nd:.1%} | {pmin}/{nd} | {1 - pmin / nd:.1%}")

# ---------------------------------------------------------------- 4. 07~09시 방향 비교(평일만)
w("")
w("== 4. 평일 07:00~09:00 ours vs opp (createdDate 기준, 길이 가중 조화평균, 가중치=config 제안 길이)")
WEEKDAYS = {"20261119": "목", "20261120": "금", "20261121": "토", "20261122": "일", "20261123": "월"}
obs = []  # (day, date, link, speed)
for r in rows:
    cd = r["created_date"]
    day, hhmmss = cd[:8], cd[8:14]
    if day not in WEEKDAYS or WEEKDAYS[day] in ("토", "일"):
        continue
    if not ("070000" <= hhmmss < "090000"):
        continue
    try:
        sp = float(r["speed"])
    except ValueError:
        continue
    if sp > 0:
        obs.append((day, cd, r["link_id"], sp))
obs_days = sorted({o[0] for o in obs})
w(f"대상일: {[(d, WEEKDAYS[d]) for d in obs_days]} (관측 {len(obs)}건)")
w("구간 | 방향 | 가중평균 km/h | 단순평균 km/h | ours/opp | 관측 수")
seg_result = {}
for seg, links, _end, desc in SEGMENTS:
    seg_links = {"ours": links, "opp": [str(int(x) - 100) for x in links]}
    vals = {}
    for direction, lids in seg_links.items():
        num = den = n = 0.0
        simple = []
        for day, _cd, lid, sp in obs:
            if lid in lids:
                wt = alloc.get(lid, its_len.get(lid, 0.0))
                num += wt
                den += wt / sp
                n += 1
                simple.append(sp)
        vals[direction] = (num / den if den else float("nan"),
                           sum(simple) / len(simple) if simple else float("nan"), int(n))
    ratio = vals["ours"][0] / vals["opp"][0] if vals["opp"][0] else float("nan")
    seg_result[seg] = (vals, ratio)
    w(f"{seg} {desc} | ours {vals['ours'][0]:.1f} (단순 {vals['ours'][1]:.1f}, n={vals['ours'][2]}) "
      f"| opp {vals['opp'][0]:.1f} (단순 {vals['opp'][1]:.1f}, n={vals['opp'][2]}) | {ratio:.2f}")

# 일별 분리
w("")
w("== 4-1. 일별 ours/opp 가중평균 (07:00~09:00)")
for seg, links, _end, desc in SEGMENTS:
    seg_links = {"ours": links, "opp": [str(int(x) - 100) for x in links]}
    cells = []
    for day in obs_days:
        line = [f"{WEEKDAYS[day]}"]
        for direction, lids in seg_links.items():
            num = den = 0.0
            for d2, _cd, lid, sp in obs:
                if d2 == day and lid in lids:
                    wt = alloc.get(lid, its_len.get(lid, 0.0))
                    num += wt
                    den += wt / sp
            line.append(f"{direction} {num / den:.1f}" if den else f"{direction} -")
        cells.append(" / ".join(line[1:]))
    w(f"{seg} {desc}: " + " | ".join(cells))

# 15분 버킷 (전 구간 ours만, 정체 시작 확인)
w("")
w("== 4-2. ours 15분 버킷 가중평균 km/h (07:00~09:00, 평일 합산)")
w("구간 | " + " | ".join(f"{m:02d}:{s:02d}" for m, s in
                         [(h, q) for h in range(7, 9) for q in (0, 15, 30, 45)]))
for seg, links, _end, desc in SEGMENTS:
    buckets = defaultdict(lambda: (0.0, 0.0))
    for day, cd, lid, sp in obs:
        if lid not in links:
            continue
        hh, mm = int(cd[8:10]), int(cd[10:12])
        b = (hh - 7) * 4 + mm // 15
        wt = alloc.get(lid, its_len.get(lid, 0.0))
        num, den = buckets[b]
        buckets[b] = (num + wt, den + wt / sp)
    row = []
    for b in range(8):
        num, den = buckets[b]
        row.append(f"{num / den:.1f}" if den else "-")
    w(f"{seg} | " + " | ".join(row))

# 06~10시 시간별 ours/opp (평일 합산)
w("")
w("== 4-3. 06:00~10:00 시간별 ours vs opp 가중평균 km/h (평일 합산)")
hours = ["06", "07", "08", "09"]
w("구간 | 방향 | " + " | ".join(f"{h}시" for h in hours))
for seg, links, _end, desc in SEGMENTS:
    seg_links = {"ours": links, "opp": [str(int(x) - 100) for x in links]}
    cells = []
    for direction, lids in seg_links.items():
        row = []
        for h in hours:
            num = den = 0.0
            for day, cd, lid, sp in obs:
                if lid in lids and cd[8:10] == h:
                    wt = alloc.get(lid, its_len.get(lid, 0.0))
                    num += wt
                    den += wt / sp
            row.append(f"{num / den:.1f}" if den else "-")
        cells.append(f"{direction}: " + " | ".join(row))
    w(f"{seg} {desc} | " + " / ".join(cells))

# ---------------------------------------------------------------- 5. 하루 전체(06~22시) ours/opp 기준선
w("")
w("== 5. 비첨두 기준선: 평일 전체(10:00~22:00) ours vs opp 가중평균 (관측 있는 날만)")
obs2 = []
for r in rows:
    cd = r["created_date"]
    day, hhmmss = cd[:8], cd[8:14]
    if day not in WEEKDAYS or WEEKDAYS[day] in ("토", "일"):
        continue
    if not ("100000" <= hhmmss < "220000"):
        continue
    try:
        sp = float(r["speed"])
    except ValueError:
        continue
    if sp > 0:
        obs2.append((day, r["link_id"], sp))
for seg, links, _end, desc in SEGMENTS:
    seg_links = {"ours": links, "opp": [str(int(x) - 100) for x in links]}
    line = [seg]
    for direction, lids in seg_links.items():
        num = den = 0.0
        for day, lid, sp in obs2:
            if lid in lids:
                wt = alloc.get(lid, its_len.get(lid, 0.0))
                num += wt
                den += wt / sp
        line.append(f"{direction} {num / den:.1f}" if den else f"{direction} -")
    w(" | ".join(line))

out.close()
print("written", sys.argv[3])
