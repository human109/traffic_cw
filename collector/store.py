"""수집 결과 저장: 원본 파일, `traffic_observation`, `collection_log` (C-01, SPEC 4.3).

이 모듈의 함수는 commit하지 않는다. commit은 진입점(`run_once`)이 한다 (C-06).
"""

from __future__ import annotations

import gzip
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from collector.paths import relative_to_root, resolve_path
from common.records import CollectionResult, ObservationRecord
from common.timeutil import KST, to_iso


def raw_path(raw_dir: Path | str, source: str, collected_at: datetime) -> Path:
    """원본 파일 경로 `{raw_dir}/{source}/{YYYYMMDD}/{HHMMSS}.xml.gz`를 돌려준다.

    상대 `raw_dir`은 저장소 루트 기준으로 해석한다(`database.db.connect`와 같은 규칙).
    저장 전에 같은 경로 파일이 이미 있었는지 확인하는 용도로도 쓴다 (M2).
    """
    to_iso(collected_at)  # tz 없는 datetime 거부
    k = collected_at.astimezone(KST)
    return resolve_path(raw_dir) / source / k.strftime("%Y%m%d") / f"{k.strftime('%H%M%S')}.xml.gz"


def save_raw(body: bytes, source: str, collected_at: datetime, raw_dir: Path) -> Path:
    """원본 응답을 `raw_path` 경로로 gzip 저장하고 경로를 돌려준다.

    같은 초에 다시 저장하면 덮어쓴다.
    """
    path = raw_path(raw_dir, source, collected_at)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(body))
    return path


def raw_file_ref(path: Path) -> str:
    """`traffic_observation.raw_file`에 기록할 문자열(기존 운영 행과 같은 형식 유지).

    저장소 루트 안의 파일은 루트 기준 상대 경로(예: `data\\raw\\its\\...`)로, 루트 밖 절대
    경로는 절대 문자열로 돌려준다. 파일은 절대 경로에 쓰고 DB에는 상대 경로를 기록한다.
    """
    return str(relative_to_root(path))


def insert_observations(conn: sqlite3.Connection, records: Iterable[ObservationRecord]) -> int:
    """레코드를 `INSERT OR IGNORE`로 넣고 새로 들어간 행 수를 돌려준다.

    중복 기준은 UNIQUE(source, link_id, source_timestamp)다.
    """
    rows = [
        (
            r.source,
            r.link_id,
            to_iso(r.source_timestamp),
            to_iso(r.collected_at),
            r.speed,
            r.travel_time,
            r.volume,
            r.congestion_code,
            r.quality_flag,
            r.raw_file,
        )
        for r in records
    ]
    if not rows:
        return 0
    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO traffic_observation"
        " (source, link_id, source_timestamp, collected_at, speed, travel_time, volume,"
        "  congestion_code, quality_flag, raw_file)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return conn.total_changes - before


def log_collection(conn: sqlite3.Connection, result: CollectionResult) -> None:
    """수집 1회 결과를 `collection_log`에 1행 기록한다."""
    conn.execute(
        "INSERT INTO collection_log"
        " (source, started_at, finished_at, status, http_status, links_expected, links_received,"
        "  record_count, error_message)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            result.source,
            to_iso(result.started_at),
            to_iso(result.finished_at),
            result.status,
            result.http_status,
            result.links_expected,
            result.links_received,
            result.record_count,
            result.error_message,
        ),
    )
