"""R-06b 2부: 출근 시간대 방향별 속도 비교를 실행한다 (R-06b 문서의 쿼리 1~3 + 등급 분포).

사용: .venv/Scripts/python.exe -I docs/research/scripts/run_direction_compare.py <repo_root> <t0> <t1> <out_txt>
예시(전체 창):
  .venv/Scripts/python.exe -I docs/research/scripts/run_direction_compare.py D:/dev/traffic_cw ^
    2026-11-20T07:00:00+09:00 2026-11-20T09:00:00+09:00 docs/research/samples/direction_compare_2026-11-20.txt

- 운영 DB는 `file:...?mode=ro` 로만 열고 절대 쓰지 않는다. 상주 수집기와 겹치지 않게 짧게 열고 닫는다.
- 쿼리 1~3은 `docs/research/R-06b-link-fix-and-direction.md`에 적어 둔 것과 같다(시각만 파라미터).
- 등급 경계는 `config/settings.py`의 grade_free_min_kmh=40, grade_slow_min_kmh=20과 같은 값을 쓴다.
- 우리 방향 = segment_link(is_mainline=1), 반대 방향 = 링크 ID-100(printf). 측도(4150149001)는 제외.
- 반대 방향 링크의 길이는 대응 우리 링크 길이로 근사한다(문서 q1과 동일).
"""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT, T0, T1, OUT = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4])
DB = Path(ROOT) / "data" / "traffic.db"
FREE, SLOW = 40.0, 20.0  # config/settings.py: grade_free_min_kmh, grade_slow_min_kmh

SEG_SQL = """
WITH seg AS (
    SELECT segment_id, link_id AS obs_link, link_length_m AS w, 'ours' AS dir
    FROM segment_link WHERE is_mainline = 1
    UNION ALL
    SELECT segment_id, printf('%010d', CAST(link_id AS INTEGER) - 100),
           link_length_m, 'opp'
    FROM segment_link WHERE is_mainline = 1
)
"""

Q1 = SEG_SQL + """
SELECT dir, segment_id,
       ROUND(SUM(w) / SUM(w / o.speed), 1) AS kmh_weighted,
       ROUND(AVG(o.speed), 1)              AS kmh_simple,
       COUNT(DISTINCT o.link_id)           AS n_links_observed,
       COUNT(*)                            AS n_obs
FROM seg s
JOIN traffic_observation o
  ON o.link_id = s.obs_link
 AND o.source = 'its' AND o.quality_flag = 'ok' AND o.speed > 0
 AND o.source_timestamp >= ? AND o.source_timestamp < ?
GROUP BY dir, segment_id
ORDER BY segment_id, dir;
"""

Q2 = SEG_SQL + """
SELECT s.segment_id, s.dir,
       (CAST(substr(o.source_timestamp, 12, 2) AS INTEGER) * 60
        + CAST(substr(o.source_timestamp, 15, 2) AS INTEGER)) / 15 AS bucket_15min,
       ROUND(AVG(o.speed), 1) AS kmh,
       COUNT(*) AS n_obs
FROM seg s
JOIN traffic_observation o
  ON o.link_id = s.obs_link
 AND o.source = 'its' AND o.quality_flag = 'ok' AND o.speed > 0
 AND o.source_timestamp >= ? AND o.source_timestamp < ?
GROUP BY s.segment_id, s.dir, bucket_15min
ORDER BY s.segment_id, s.dir, bucket_15min;
"""

Q3 = """
SELECT sl.segment_id, sl.link_id, sl.is_mainline, COUNT(o.id) AS n_obs
FROM segment_link sl
LEFT JOIN traffic_observation o
  ON o.link_id = sl.link_id AND o.source = 'its' AND o.quality_flag = 'ok'
 AND o.source_timestamp >= ? AND o.source_timestamp < ?
GROUP BY sl.segment_id, sl.link_id, sl.is_mainline
HAVING n_obs = 0;
"""

Q4 = SEG_SQL + """
SELECT s.segment_id, s.dir,
       CASE WHEN o.speed >= 40 THEN 'free'
            WHEN o.speed >= 20 THEN 'slow'
            ELSE 'congested' END AS grade,
       COUNT(*) AS n_obs
FROM seg s
JOIN traffic_observation o
  ON o.link_id = s.obs_link
 AND o.source = 'its' AND o.quality_flag = 'ok' AND o.speed > 0
 AND o.source_timestamp >= ? AND o.source_timestamp < ?
GROUP BY s.segment_id, s.dir, grade
ORDER BY s.segment_id, s.dir, grade;
"""

conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
try:
    q1 = list(conn.execute(Q1, (T0, T1)))
    q2 = list(conn.execute(Q2, (T0, T1)))
    q3 = list(conn.execute(Q3, (T0, T1)))
    q4 = list(conn.execute(Q4, (T0, T1)))
finally:
    conn.close()

out: list[str] = []
out.append(f"R-06b 방향 비교 실행 결과: 창 {T0} ~ {T1} (운영 DB 읽기 전용, 쓰기 없음)")
out.append(f"등급 경계: 원활 >= {FREE:.0f}km/h, 서행 {SLOW:.0f}~{FREE:.0f}, 정체 < {SLOW:.0f} (config/settings.py)")
out.append("")


def bucket_label(n: int) -> str:
    return f"{(n * 15) // 60:02d}:{(n * 15) % 60:02d}"


# --- q1: 구간 × 방향 요약 + 비율
out.append("## q1 구간 x 방향 요약 (kmh_weighted = 길이 가중 조화평균, 관측 단위)")
out.append("| 구간 | 방향 | 가중평균 km/h | 단순평균 km/h | 관측 링크 | 관측 수 | ours/opp |")
out.append("|---|---|---|---|---|---|---|")
w1: dict[tuple[str, str], dict] = {}
for dir_, seg, kw, ks, nl, no in q1:
    w1[(seg, dir_)] = {"kw": kw, "ks": ks, "nl": nl, "no": no}
for seg in sorted({s for s, _ in w1}):
    ours, opp = w1.get((seg, "ours")), w1.get((seg, "opp"))
    ratio = f"{ours['kw'] / opp['kw']:.2f}" if ours and opp and opp["kw"] else "-"
    for dir_ in ("ours", "opp"):
        v = w1.get((seg, dir_))
        if v:
            out.append(f"| {seg} | {dir_} | {v['kw']} | {v['ks']} | {v['nl']} | {v['no']} | {ratio if dir_ == 'ours' else ''} |")
out.append("")

# --- q2: 15분 버킷 표
b2: dict[tuple[str, str, int], dict] = {}
for seg, dir_, b, kmh, no in q2:
    b2[(seg, dir_, b)] = {"kmh": kmh, "no": no}
buckets = sorted({b for _, _, b in b2})
out.append("## q2 15분 버킷 평균 km/h (행=구간x방향, 값 없으면 '-')")
out.append("| 구간 | 방향 | " + " | ".join(bucket_label(b) for b in buckets) + " |")
out.append("|---|---|" + "---|" * len(buckets))
for seg in sorted({s for s, _, _ in b2}):
    for dir_ in ("ours", "opp"):
        cells = []
        for b in buckets:
            v = b2.get((seg, dir_, b))
            cells.append(f"{v['kmh']} ({v['no']})" if v else "-")
        out.append(f"| {seg} | {dir_} | " + " | ".join(cells) + " |")
out.append("")

# --- q3: 창에서 관측 0건 링크
out.append("## q3 창에서 관측 0건인 segment_link 행")
out.append("| 구간 | link_id | is_mainline | 관측 수 |")
out.append("|---|---|---|---|")
for seg, lid, main, no in q3:
    out.append(f"| {seg} | {lid} | {main} | {no} |")
out.append("")

# --- q4: 등급 분포
out.append("## q4 원관측 속도 등급 분포 (관측 수)")
out.append("| 구간 | 방향 | 원활(>=40) | 서행(20~40) | 정체(<20) | 합계 |")
out.append("|---|---|---|---|---|---|")
g: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"free": 0, "slow": 0, "congested": 0})
for seg, dir_, grade, no in q4:
    g[(seg, dir_)][grade] += no
for (seg, dir_) in sorted(g):
    v = g[(seg, dir_)]
    out.append(f"| {seg} | {dir_} | {v['free']} | {v['slow']} | {v['congested']} | {sum(v.values())} |")
out.append("")

# --- 판정 계산 (버킷 표를 만든 뒤)
out.append("## 판정 (문서 기준: ours<opp 이고 07:30~08:30 버킷(30~34)에서 ours가 opp보다 20% 이상 낮으면 적중)")
out.append("| 구간 | ours<opp | ours/opp(전체 창) | 07:30~08:30 ours | 07:30~08:30 opp | ours/opp(첨두) | 20% 미달 |")
out.append("|---|---|---|---|---|---|---|")
for seg in sorted({s for s, _ in w1}):
    ours, opp = w1.get((seg, "ours")), w1.get((seg, "opp"))
    if not (ours and opp and opp["kw"]):
        out.append(f"| {seg} | - | - | - | - | - | - |")
        continue
    is_lower = ours["kw"] < opp["kw"]
    def peak(d: str):
        vals = [v["kmh"] for (s, dd, b), v in b2.items() if s == seg and dd == d and 30 <= b <= 34]
        return f"{sum(vals) / len(vals):.1f} ({len(vals)}버킷)" if vals else "-"
    po, pp = peak("ours"), peak("opp")
    try:
        po_v, pp_v = float(po.split(" ")[0]), float(pp.split(" ")[0])
        peak_ratio, under20 = (f"{po_v / pp_v:.2f}" if pp_v else "-"), ("예" if pp_v and po_v <= 0.8 * pp_v else "아니오")
    except ValueError:
        peak_ratio, under20 = "-", "-"
    out.append(f"| {seg} | {'예' if is_lower else '아니오'} | {ours['kw'] / opp['kw']:.2f} | {po} | {pp} | {peak_ratio} | {under20} |")

OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"wrote {OUT} ({len(out)} lines)")
