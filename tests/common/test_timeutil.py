from datetime import datetime, timedelta, timezone

import pytest

from common.timeutil import KST, floor_5min, parse_compact_kst, parse_iso, to_iso


def test_to_iso_format() -> None:
    assert to_iso(datetime(2026, 11, 18, 7, 3, 9, 500, tzinfo=KST)) == "2026-11-18T07:03:09+09:00"


def test_to_iso_converts_utc() -> None:
    utc = datetime(2026, 11, 17, 22, 0, 0, tzinfo=timezone.utc)
    assert to_iso(utc) == "2026-11-18T07:00:00+09:00"


def test_naive_rejected() -> None:
    naive = datetime(2026, 11, 18, 7, 0, 0)
    with pytest.raises(ValueError):
        to_iso(naive)
    with pytest.raises(ValueError):
        floor_5min(naive)
    with pytest.raises(ValueError):
        parse_iso("2026-11-18T07:00:00")


def test_parse_iso_roundtrip() -> None:
    dt = parse_iso("2026-11-18T07:00:00+09:00")
    assert dt == datetime(2026, 11, 18, 7, 0, 0, tzinfo=KST)
    assert dt.utcoffset() == timedelta(hours=9)


def test_floor_5min() -> None:
    assert floor_5min(datetime(2026, 11, 18, 7, 4, 59, 999, tzinfo=KST)) == datetime(2026, 11, 18, 7, 0, tzinfo=KST)
    assert floor_5min(datetime(2026, 11, 18, 7, 5, 0, tzinfo=KST)) == datetime(2026, 11, 18, 7, 5, tzinfo=KST)


def test_floor_5min_returns_kst() -> None:
    utc = datetime(2026, 11, 17, 22, 7, 0, tzinfo=timezone.utc)
    result = floor_5min(utc)
    assert result == datetime(2026, 11, 18, 7, 5, tzinfo=KST)
    assert result.utcoffset() == timedelta(hours=9)


def test_parse_compact_kst() -> None:
    assert parse_compact_kst("20201130144001") == datetime(2020, 11, 30, 14, 40, 1, tzinfo=KST)


def test_parse_compact_kst_invalid() -> None:
    with pytest.raises(ValueError):
        parse_compact_kst("2020113014")
