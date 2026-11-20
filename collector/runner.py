"""수집 1회 실행 (`collector.run_once`, C-06). 상태 판정 규칙은 SPEC 4.5와 Slice 0 Task 5를 따른다."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from collector.base import FetchResult, SourceAdapter
from collector.its import ItsAdapter, mask_secret
from collector.store import insert_observations, log_collection, raw_file_ref, raw_path, save_raw
from common.logsetup import get_logger
from common.records import CollectionResult, CollectionStatus, ObservationRecord
from common.timeutil import now_kst, require_aware, to_iso
from config.settings import Settings

log = get_logger(__name__)

NO_ITEMS_ERROR = "응답에 읽을 수 있는 item 없음"
NO_STORE_ROAD_ERROR = "저장 대상 도로 item 없음"


def _store_scope(
    records: list[ObservationRecord],
    source: str,
    settings: Settings,
    targets: frozenset[str] | set[str],
) -> list[ObservationRecord]:
    """DB에 저장할 레코드만 남긴다 (C-02 v2 + Slice 0 리뷰 M1 저장 범위).

    ITS는 `road_name`이 `settings.its_store_road_names`에 속하거나 **또는** `link_id`가
    현재 유효한 대상 링크(`segment_link`)인 레코드만 저장한다. 대상 링크는 도로명과 무관하게
    구간 집계에 필요하다. 원본 파일은 응답 전체를 보관하므로 나머지는 원본에서 재적재할 수 있다.
    다른 수집원은 아직 저장 범위 규칙이 없어 그대로 둔다.
    """
    if source != "its":
        return records
    allowed = set(settings.its_store_road_names)
    return [r for r in records if r.road_name in allowed or r.link_id in targets]


def _target_links(conn: sqlite3.Connection, now: datetime) -> set[str]:
    """`now` 시점에 유효한 대상 링크 ID 집합.

    `segment_link.source`로 거르지 않고 `link_id`로만 대조한다. C-01 v1.1 불변 조건:
    `segment_link.source`는 링크 ID 체계의 출처(`moct_nodelink` 등)이고 수집원(`its`)과 다르며,
    ITS·경찰청 UTIC 모두 표준노드링크 ID를 쓴다.
    """
    t = to_iso(now)
    rows = conn.execute(
        "SELECT DISTINCT link_id FROM segment_link"
        " WHERE valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)",
        (t, t),
    ).fetchall()
    return {r[0] for r in rows}


def _collect(
    now: datetime,
    conn: sqlite3.Connection,
    adapter: SourceAdapter,
    settings: Settings,
    clock: Callable[[], datetime],
) -> tuple[CollectionStatus, int | None, int | None, int, int, str | None]:
    """(status, http_status, links_expected, links_received, record_count, error) 를 돌려준다."""
    http_status: int | None = None
    try:
        targets = _target_links(conn, now)
        expected = len(targets) or None

        fetched: FetchResult = adapter.fetch(now)
        http_status = fetched.http_status
        # I5: collected_at은 응답을 실제로 받은(fetch가 끝난) 시각이다. 재시도로 오래 걸린 회차를
        # 시작 시각으로 기록하면 `collected_at <= until` 미래 정보 금지 규칙(SPEC 6.6)을 해친다.
        collected_at = clock()
        require_aware(collected_at)

        raw_file: str | None = None
        raw_saved: Path | None = None
        raw_existed = False
        if fetched.body:
            try:
                path = raw_path(Path(settings.raw_dir), adapter.name, collected_at)
                raw_existed = path.exists()
                raw_saved = save_raw(fetched.body, adapter.name, collected_at, Path(settings.raw_dir))
                # DB에는 기존 운영 행과 같은 루트 기준 상대 경로를 기록한다(루트 밖이면 절대 경로).
                raw_file = raw_file_ref(raw_saved)
            except OSError as e:
                log.error("원본 저장 실패: %s", e)

        if adapter.is_auth_error(fetched):
            return "auth_error", http_status, expected, 0, 0, fetched.error or "인증 오류"
        if fetched.error is not None or fetched.body is None:
            return "failed", http_status, expected, 0, 0, fetched.error or "빈 응답"

        records: list[ObservationRecord] = adapter.parse(fetched.body, collected_at)
        if not records:
            # resultCode=0이어도 읽을 레코드가 없으면 실패다. no_update는 "읽었지만 모두 이미 저장됨"만 뜻한다.
            return "failed", http_status, expected, 0, 0, NO_ITEMS_ERROR
        records = _store_scope(records, adapter.name, settings, targets)
        if not records:
            return "failed", http_status, expected, 0, 0, NO_STORE_ROAD_ERROR
        if raw_file is not None:
            records = [replace(r, raw_file=raw_file) for r in records]
        received_ids = {r.link_id for r in records}
        received = len(received_ids & targets) if targets else len(received_ids)

        inserted = insert_observations(conn, records)
        if inserted == 0:
            # M2: 응답의 모든 레코드가 이미 DB에 있으면(같은 createdDate 반복 조회) 원본 파일을
            # 다시 쓰지 않는다. 이번 회차에 새로 쓴 파일만 지운다. 같은 초에 직전 회차 파일이
            # 덮어써진 경우에는 지우지 않아 직전 원본을 보존한다.
            # 파싱 실패 등 진단이 필요한 회차는 위에서 저장한 원본을 그대로 둔다.
            if raw_saved is not None and not raw_existed:
                try:
                    raw_saved.unlink()
                except OSError as e:
                    log.error("원본 파일 삭제 실패: %s", e)
            return "no_update", http_status, expected, received, 0, None
        if targets and not targets <= received_ids:
            missing = len(targets - received_ids)
            return "partial", http_status, expected, received, inserted, f"대상 링크 {missing}개 응답 없음"
        return "success", http_status, expected, received, inserted, None
    except Exception as e:  # 진입점은 예외를 밖으로 던지지 않는다 (C-06)
        conn.rollback()
        # traceback에는 키가 들어간 URL이 섞일 수 있어 가린 메시지만 남긴다.
        message = mask_secret(f"{type(e).__name__}: {e}", settings.its_api_key)
        log.error("수집 실패: %s", message)
        return "failed", http_status, None, 0, 0, message


def run_once(
    now: datetime,
    conn: sqlite3.Connection | None = None,
    adapter: SourceAdapter | None = None,
    *,
    settings: Settings | None = None,
    clock: Callable[[], datetime] = now_kst,
) -> CollectionResult:
    """수집을 1회 실행하고 `collection_log`에 결과를 남긴다.

    상태: 인증 오류 `auth_error` / 그 밖의 fetch·parse 실패 `failed` / 신규 0건 `no_update` /
    대상 링크 중 응답에 없는 것이 있으면 `partial` / 그 밖에는 `success`.
    `now`가 timezone 정보 없는 datetime이면 `ValueError`. 그 밖의 예외는 밖으로 던지지 않는다.

    - `conn=None`이면 `database.db.connect()`로 열고 끝나면 닫는다. `conn`을 받으면 닫지 않는다.
    - 수집 중 예외가 나면 호출자가 넘긴 `conn`도 rollback한다(그 전의 미커밋 변경도 함께 취소된다).
    - 준비 단계(`get_settings()`, adapter 생성, DB 연결)의 예외도 던지지 않고 `failed`를 반환한다.
      이때 DB 연결을 얻지 못했으면 `collection_log` 기록은 생략하고 에러 로그만 남긴다.
    - C-06 시그니처에 더해 키워드 전용 `settings`를 받는다(테스트에서 raw_dir 등을 바꾸기 위함).
    - 키워드 전용 `clock`은 레코드의 `collected_at`(응답 수신 시각)을 얻는 함수다. 기본은 실제
      시각(`now_kst`)이고, 넘겨받은 `now`는 `started_at`과 대상 링크 유효 판정에만 쓴다.
      `clock`이 timezone 정보 없는 datetime을 반환하면 그 회차는 `failed`가 된다. 테스트에서
      이 인자로 시계를 고정한다.
    - `no_update` 회차(응답의 모든 레코드가 이미 저장됨)는 원본 파일을 새로 쓰지 않는다.
      파싱 실패 등 진단이 필요한 회차는 원본을 저장한다.
    """
    to_iso(now)  # tz 없는 datetime 거부
    started = time.monotonic()
    own_conn = conn is None
    source = adapter.name if adapter is not None else "its"
    secret: str | None = settings.its_api_key if settings is not None else None

    def _finish(
        status: CollectionStatus,
        http_status: int | None,
        expected: int | None,
        received: int,
        count: int,
        error: str | None,
    ) -> CollectionResult:
        result = CollectionResult(
            source=source,
            status=status,
            started_at=now,
            finished_at=now + timedelta(seconds=time.monotonic() - started),
            http_status=http_status,
            links_expected=expected,
            links_received=received,
            record_count=count,
            error_message=mask_secret(error, secret) if error is not None else None,
        )
        if conn is not None:
            try:
                log_collection(conn, result)
                conn.commit()
            except Exception as e:
                conn.rollback()
                log.error("collection_log 기록 실패: %s", mask_secret(f"{type(e).__name__}: {e}", secret))
        else:
            log.error("DB 연결이 없어 collection_log를 남기지 못했다")
        log.info(
            "수집 %s: status=%s records=%d links=%s/%s",
            result.source, result.status, result.record_count, result.links_received, result.links_expected,
        )
        return result

    try:
        try:
            if settings is None:
                from config.settings import get_settings

                settings = get_settings()
                secret = settings.its_api_key
            if adapter is None:
                adapter = ItsAdapter(settings)
                source = adapter.name
            if conn is None:
                from database.db import connect  # Task 4에서 제공 (C-06)

                conn = connect()
        except Exception as e:
            message = mask_secret(f"수집 준비 실패: {type(e).__name__}: {e}", secret)
            log.error("%s", message)
            return _finish("failed", None, None, 0, 0, message)

        return _finish(*_collect(now, conn, adapter, settings, clock))
    finally:
        if own_conn and conn is not None:
            conn.close()
