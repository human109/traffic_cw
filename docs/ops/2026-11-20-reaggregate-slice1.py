"""운영 DB를 Slice 1 규칙으로 다시 집계 (Slice 1 Task 8, 일회성 운영 작업 기록).

1. 처음부터 잘못 매핑된 4140068801 행을 '유효했던 적 없음'으로 닫는다(valid_to = valid_from).
   ITS는 이 구간을 처음부터 4140068800으로 줬으므로(R-06b) 과거 bin의 기대 링크에서도 빠져야 한다.
2. segment_traffic_5min을 비우고 첫 관측 bin부터 now까지 한 번에(시간순) 다시 집계한다.

실행: .venv\\Scripts\\python -I docs\\ops\\2026-11-20-reaggregate-slice1.py <저장소 루트>
"""
import sys

sys.path.insert(0, sys.argv[1])
from common.timeutil import floor_5min, now_kst, parse_iso  # noqa: E402
from database.db import connect  # noqa: E402
import preprocessing  # noqa: E402

conn = connect()
conn.execute(
    "UPDATE segment_link SET valid_to = valid_from WHERE link_id = '4140068801' AND valid_to IS NOT NULL"
)
first = conn.execute("SELECT MIN(source_timestamp) FROM traffic_observation").fetchone()[0]
now = now_kst()
lookback = int((now - floor_5min(parse_iso(first))).total_seconds() // 60) + 5
conn.execute("DELETE FROM segment_traffic_5min")
conn.commit()
n = preprocessing.run(now, conn=conn, lookback_minutes=lookback)
flags = conn.execute(
    "SELECT quality_flag, COUNT(*) FROM segment_traffic_5min GROUP BY quality_flag ORDER BY 2 DESC"
).fetchall()
print("rows", n, "lookback_min", lookback, "flags", [tuple(f) for f in flags])
print("S3 last", tuple(conn.execute(
    "SELECT bin_time, speed, quality_flag, n_links_observed, n_links_expected FROM segment_traffic_5min"
    " WHERE segment_id='S3' ORDER BY bin_time DESC LIMIT 1").fetchone()))
conn.close()
