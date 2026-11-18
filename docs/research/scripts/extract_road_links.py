"""표준노드링크 배포본에서 특정 도로명 링크와 인접 링크·노드를 추출한다.

표준 라이브러리만 사용한다. 원본 파일은 읽기만 한다.

사용:
  python -I extract_road_links.py <NODELINKDATA 디렉터리> <출력 JSON 경로> [도로명]

출력 JSON:
  links:  도로명 일치 링크 + 그 노드에 접한 인접 링크 (속성, 시·종점 좌표, 기하 길이)
  nodes:  위 링크들이 참조하는 노드 (이름, 유형, 좌표)
  multilink_ids: MULTILINK.dbf에서 도로명이 일치하는 링크 ID
"""
from __future__ import annotations

import json
import math
import os
import struct
import sys

ENC = "cp949"


def dbf_iter(path: str):
    """DBF 레코드를 (index, dict)로 순회한다."""
    with open(path, "rb") as f:
        head = f.read(32)
        nrec, hlen, rlen = struct.unpack("<IHH", head[4:12])
        fields = []
        while True:
            d = f.read(32)
            if d[0] == 0x0D:
                break
            fields.append((d[:11].split(b"\x00")[0].decode("ascii"), d[16]))
        f.seek(hlen)
        chunk = 20000
        idx = 0
        while idx < nrec:
            n = min(chunk, nrec - idx)
            buf = f.read(rlen * n)
            for k in range(n):
                rec = buf[k * rlen:(k + 1) * rlen]
                yield idx + k, rec, fields
            idx += n


def decode(rec: bytes, fields) -> dict:
    out = {}
    pos = 1
    for name, flen in fields:
        out[name] = rec[pos:pos + flen].decode(ENC, errors="replace").strip()
        pos += flen
    return out


def field_slice(fields, name):
    pos = 1
    for n, flen in fields:
        if n == name:
            return pos, pos + flen
        pos += flen
    raise KeyError(name)


def shp_geom(shp, shx, index: int):
    """SHP polyline/point 레코드에서 점 목록을 읽는다."""
    shx.seek(100 + index * 8)
    off, _clen = struct.unpack(">ii", shx.read(8))
    shp.seek(off * 2 + 8)
    stype = struct.unpack("<i", shp.read(4))[0]
    if stype == 1:
        x, y = struct.unpack("<dd", shp.read(16))
        return [(x, y)]
    if stype in (3, 13, 23):
        shp.read(32)
        nparts, npts = struct.unpack("<ii", shp.read(8))
        shp.read(4 * nparts)
        pts = struct.unpack("<" + "d" * (2 * npts), shp.read(16 * npts))
        return [(pts[i], pts[i + 1]) for i in range(0, len(pts), 2)]
    return []


def main() -> None:
    base, out_path = sys.argv[1], sys.argv[2]
    road = sys.argv[3] if len(sys.argv) > 3 else "창원대로"
    road_b = road.encode(ENC)

    # MULTILINK 도로명
    multi_ids = set()
    for _i, rec, fields in dbf_iter(os.path.join(base, "MULTILINK.dbf")):
        if road_b in rec:
            d = decode(rec, fields)
            if road in d["ROAD_NAME"]:
                multi_ids.add(d["LINK_ID"])

    link_dbf = os.path.join(base, "MOCT_LINK.dbf")
    # 1차: 도로명 일치 링크
    hit = {}
    node_set = set()
    for i, rec, fields in dbf_iter(link_dbf):
        lid_s = field_slice(fields, "LINK_ID")
        if road_b in rec or rec[lid_s[0]:lid_s[1]].decode("ascii").strip() in multi_ids:
            d = decode(rec, fields)
            if road in d["ROAD_NAME"] or d["LINK_ID"] in multi_ids:
                d["_idx"] = i
                d["_match"] = "name" if road in d["ROAD_NAME"] else "multilink"
                hit[d["LINK_ID"]] = d
                node_set.add(d["F_NODE"])
                node_set.add(d["T_NODE"])
    # 2차: 인접 링크(같은 노드에 접한 링크)
    fs = ts = None
    for i, rec, fields in dbf_iter(link_dbf):
        if fs is None:
            fs = field_slice(fields, "F_NODE")
            ts = field_slice(fields, "T_NODE")
        fn = rec[fs[0]:fs[1]].decode("ascii", errors="replace").strip()
        tn = rec[ts[0]:ts[1]].decode("ascii", errors="replace").strip()
        if fn in node_set or tn in node_set:
            d = decode(rec, fields)
            if d["LINK_ID"] not in hit:
                d["_idx"] = i
                d["_match"] = "adjacent"
                hit[d["LINK_ID"]] = d
    all_nodes = set()
    for d in hit.values():
        all_nodes.add(d["F_NODE"])
        all_nodes.add(d["T_NODE"])

    # 기하
    with open(os.path.join(base, "MOCT_LINK.shp"), "rb") as shp, open(
        os.path.join(base, "MOCT_LINK.shx"), "rb"
    ) as shx:
        for d in hit.values():
            pts = shp_geom(shp, shx, d["_idx"])
            d["_start"] = pts[0] if pts else None
            d["_end"] = pts[-1] if pts else None
            d["_geom_len"] = sum(
                math.dist(pts[k], pts[k + 1]) for k in range(len(pts) - 1)
            )
            d["_npts"] = len(pts)

    nodes = {}
    for i, rec, fields in dbf_iter(os.path.join(base, "MOCT_NODE.dbf")):
        nid = rec[1:11].decode("ascii", errors="replace").strip()
        if nid in all_nodes:
            d = decode(rec, fields)
            d["_idx"] = i
            nodes[nid] = d
    with open(os.path.join(base, "MOCT_NODE.shp"), "rb") as shp, open(
        os.path.join(base, "MOCT_NODE.shx"), "rb"
    ) as shx:
        for d in nodes.values():
            pts = shp_geom(shp, shx, d["_idx"])
            d["_xy"] = pts[0] if pts else None

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {"links": list(hit.values()), "nodes": nodes, "multilink_ids": sorted(multi_ids)},
            f,
            ensure_ascii=False,
            indent=1,
        )
    print(f"name/multilink links={sum(1 for d in hit.values() if d['_match'] != 'adjacent')} "
          f"adjacent={sum(1 for d in hit.values() if d['_match'] == 'adjacent')} nodes={len(nodes)}")


if __name__ == "__main__":
    main()
