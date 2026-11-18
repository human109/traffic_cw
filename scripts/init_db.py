"""운영 DB를 초기화하고 구간·링크 시드를 적재한다.

실행(저장소 루트): `python -m scripts.init_db` 또는 `python scripts/init_db.py`
DB 경로는 `config.settings.get_settings().db_path`(환경변수 DB_PATH로 변경 가능).
상대경로면 실행 위치가 아니라 저장소 루트 기준으로 해석한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    # `python scripts/init_db.py`로 실행해도 저장소 루트 패키지를 import할 수 있게 한다.
    sys.path.insert(0, str(ROOT))

from common.logsetup import get_logger  # noqa: E402
from config.segments import SEGMENTS  # noqa: E402
from config.settings import get_settings  # noqa: E402
from database.db import connect, init_db  # noqa: E402
from scripts.load_segments import load  # noqa: E402

LINKS_CSV = ROOT / "config" / "segment_links.csv"

log = get_logger("scripts.init_db")


def main() -> int:
    """`data/` 디렉터리를 만들고 스키마 생성과 시드 적재를 수행한다."""
    db_path = Path(get_settings().db_path)
    if not db_path.is_absolute():
        # 실행 위치와 상관없이 저장소 루트 기준으로 해석한다.
        db_path = ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        init_db(conn)
        n_seg, n_link = load(conn, SEGMENTS, LINKS_CSV)
    finally:
        conn.close()
    log.info("DB 초기화 완료: %s (구간 %d, 링크 %d)", db_path, n_seg, n_link)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
