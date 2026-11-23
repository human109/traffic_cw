"""scripts._console 표준출력 인코딩 방어 테스트 (D-DAT-06).

PowerShell 리디렉션(`| Out-File`)·파이프에서 표준출력이 cp949(엄격)로 다시 열려도 CLI가
`UnicodeEncodeError`로 죽지 않는 것을 확인한다. 운영 DB는 쓰지 않는다.
"""

from __future__ import annotations

import io
import sys

import pytest

from scripts._console import make_stdout_lenient


class _NoReconfigure:
    """`reconfigure`가 없는 스트림 대역(pytest 캡처 객체처럼). 테스트 안에서만 쓴다."""

    def __init__(self) -> None:
        self.written: list[str] = []

    def write(self, s: str) -> int:
        self.written.append(s)
        return len(s)


class _ClosedStream:
    """`reconfigure`가 닫힌 스트림처럼 ValueError를 내는 대역. 테스트 안에서만 쓴다."""

    def reconfigure(self, **kwargs: object) -> None:
        raise ValueError("I/O operation on closed file")


def test_ignores_stream_without_reconfigure(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _NoReconfigure()
    monkeypatch.setattr(sys, "stdout", s)
    monkeypatch.setattr(sys, "stderr", s)
    make_stdout_lenient()  # reconfigure가 없으면 건드리지 않고 조용히 지나간다
    assert s.written == []


def test_swallows_reconfigure_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", _ClosedStream())
    monkeypatch.setattr(sys, "stderr", _ClosedStream())
    make_stdout_lenient()  # 출력 방어가 CLI를 새로 죽이면 안 된다


def test_makes_strict_cp949_stream_lenient(monkeypatch: pytest.MonkeyPatch) -> None:
    buf = io.BytesIO()
    stream = io.TextIOWrapper(buf, encoding="cp949", errors="strict", newline="\n")
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "stderr", stream)

    make_stdout_lenient()
    print("em dash: —")  # 원래는 cp949에서 UnicodeEncodeError
    stream.flush()
    assert "em dash: ?" in buf.getvalue().decode("cp949")  # 대체 문자로 넘어간다
