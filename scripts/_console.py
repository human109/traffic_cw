"""CLI 콘솔 출력 인코딩 방어 (D-DAT-06).

Windows PowerShell에서 `python -m scripts.collection_rate | Out-File ...`처럼 리디렉션하거나
파이프로 넘기면 표준출력이 cp949(엄격)로 다시 열려, cp949에 없는 문자(예: '—')를 print할 때
`UnicodeEncodeError`로 죽는다. CLI는 인코딩 환경과 무관하게 끝까지 결과를 보여 줘야 하므로
`main()` 시작에서 표준출력의 `errors`를 `replace`로 바꿔 둔다(문자는 애초에 ASCII로 쓴다).
"""

from __future__ import annotations

import sys


def make_stdout_lenient() -> None:
    """`sys.stdout`·`sys.stderr`의 인코딩 오류를 예외 대신 대체 문자로 처리한다 (D-DAT-06).

    - `reconfigure`가 없는 스트림(pytest의 캡처 객체 등)은 건드리지 않는다.
    - 이미 닫혔거나 재설정할 수 없는 스트림(`ValueError`·`OSError`, `io.UnsupportedOperation`)도
      조용히 넘긴다. 출력 방어가 CLI를 새로 죽이면 안 된다.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):
            pass
