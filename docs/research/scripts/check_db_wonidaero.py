"""R-09 보조: 운영 DB(읽기 전용)에 원이대로 관측이 있는지 확인한다.

사용: python -I check_db_wonidaero.py
"""
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")
conn = sqlite3.connect("file:data/traffic.db?mode=ro", uri=True)
cur = conn.cursor()
try:
    cur.execute("SELECT road_name, COUNT(*) FROM traffic_observation GROUP BY road_name")
    print("road_name별 행 수:", cur.fetchall())
except sqlite3.OperationalError as e:
    print("road_name 컬럼 없음(C-02 v2 이전 스키마):", e)
cur.execute("SELECT COUNT(*) FROM traffic_observation WHERE link_id LIKE '41501459%' OR link_id LIKE '41501451%' OR link_id='4150054500'")
print("원이대로 대표 링크 행 수:", cur.fetchone())
cur.execute("SELECT MIN(source_timestamp), MAX(source_timestamp), COUNT(*) FROM traffic_observation")
print("전체 관측 범위:", cur.fetchone())
conn.close()
