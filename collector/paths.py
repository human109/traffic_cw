"""저장소 루트 기준 경로 해석. `database.db.connect`가 상대 `db_path`를 해석하는 것과 같은 규칙이다.

`database.db`의 루트 상수는 C-06 진입점이 아니므로 같은 규칙을 수집기 안에 둔다
(C-06 v2 불변 조건: 상대 경로는 실행 위치가 아니라 저장소 루트 기준).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # 저장소 루트 (collector/paths.py의 부모)


def resolve_path(path: str | Path) -> Path:
    """상대 경로는 저장소 루트 기준으로 해석해 돌려준다. 절대 경로는 그대로 둔다."""
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def relative_to_root(path: str | Path) -> Path:
    """루트 안의 경로는 루트 기준 상대 경로로, 루트 밖 절대 경로는 그대로 돌려준다."""
    p = Path(path)
    try:
        return p.relative_to(ROOT)
    except ValueError:
        return p
