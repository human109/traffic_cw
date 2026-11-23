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
from common.timeutil import now_kst  # noqa: E402
from config.segments import SEGMENTS  # noqa: E402
from config.settings import get_settings  # noqa: E402
from database.db import connect, init_db  # noqa: E402
from scripts._console import make_stdout_lenient  # noqa: E402
from scripts.load_calendar import load as load_calendar  # noqa: E402
from scripts.load_segments import load  # noqa: E402

LINKS_CSV = ROOT / "config" / "segment_links.csv"

log = get_logger("scripts.init_db")


def main() -> int:
    """DB 파일을 새로 만들고 스키마 생성, 구간·링크 시드, 올해·내년 달력 적재를 수행한다.

    로그가 cp949 콘솔·리디렉션에서 인코딩 오류로 죽지 않게 표준출력 오류 처리를 완화한다(D-DAT-06).
    """
    make_stdout_lenient()
    db_path = Path(get_settings().db_path)
    if not db_path.is_absolute():
        # 실행 위치와 상관없이 저장소 루트 기준으로 해석한다(connect와 같은 기준).
        db_path = ROOT / db_path
    conn = connect(db_path, create=True)  # 새 DB를 만들 수 있는 곳은 여기뿐이다(C-06 v2)
    try:
        init_db(conn)
        n_seg, n_link = load(conn, SEGMENTS, LINKS_CSV)
        n_cal = load_calendar(conn, [now_kst().year, now_kst().year + 1])
    finally:
        conn.close()
    log.info("DB 초기화 완료: %s (구간 %d, 링크 %d, 달력 %d행)", db_path, n_seg, n_link, n_cal)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
