"""R-09 보조: ITS 원본 gzip XML에서 특정 roadName의 item을 모아 CSV로 저장한다.

사용: python -I extract_its_road.py <raw 디렉터리(data/raw/its)> <출력 CSV> [roadName]
원본 파일은 읽기 전용이다. 표준 라이브러리만 사용한다.

CSV 열: file, created_date, road_name, link_id, start_node, end_node, speed, travel_time
"""
from __future__ import annotations

import csv
import gzip
import os
import re
import sys

ENC = "utf-8"
ITEM_RE = re.compile(r"<item>(.*?)</item>", re.S)


def field(item: str, name: str) -> str:
    m = re.search(rf"<{name}>(.*?)</{name}>", item, re.S)
    return m.group(1).strip() if m else ""


def main() -> None:
    base, out_path = sys.argv[1], sys.argv[2]
    road = sys.argv[3] if len(sys.argv) > 3 else "원이대로"
    rows = []
    for day in sorted(os.listdir(base)):
        daydir = os.path.join(base, day)
        if not os.path.isdir(daydir):
            continue
        for fn in sorted(os.listdir(daydir)):
            if not fn.endswith(".xml.gz"):
                continue
            path = os.path.join(daydir, fn)
            try:
                with gzip.open(path, "rt", encoding=ENC) as f:
                    text = f.read()
            except (OSError, EOFError) as e:
                print(f"SKIP {path}: {e}")
                continue
            if road not in text:
                continue
            n_created = 0
            for m in ITEM_RE.finditer(text):
                item = m.group(1)
                rn = field(item, "roadName")
                if rn != road:
                    continue
                cd = field(item, "createdDate")
                rows.append({
                    "file": f"{day}/{fn}",
                    "created_date": cd,
                    "road_name": rn,
                    "link_id": field(item, "linkId"),
                    "start_node": field(item, "startNodeId"),
                    "end_node": field(item, "endNodeId"),
                    "speed": field(item, "speed"),
                    "travel_time": field(item, "travelTime"),
                })
                n_created += 1
            if n_created == 0:
                print(f"NOITEM {path}")
    cols = ["file", "created_date", "road_name", "link_id", "start_node", "end_node", "speed", "travel_time"]
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    files = len({r["file"] for r in rows})
    print(f"rows={len(rows)} files_with_items={files} links={len({r['link_id'] for r in rows})}")


if __name__ == "__main__":
    main()
