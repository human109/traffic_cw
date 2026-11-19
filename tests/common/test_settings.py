import pytest

from config import settings as settings_mod
from config.segments import SEGMENTS


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("ITS_API_KEY", "POLICE_UTIC_API_KEY", "DB_PATH"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(settings_mod, "_load_dotenv", lambda: None)


def test_settings_defaults(clean_env: None) -> None:
    s = settings_mod.get_settings()
    assert s.horizons == (5, 10, 15, 30)
    assert s.stale_minutes == 10
    assert s.db_path == "data/traffic.db"
    assert s.its_api_key is None
    assert s.grade_free_min_kmh == 40.0
    assert s.grade_slow_min_kmh == 20.0


def test_settings_env_override(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_PATH", "x/y.db")
    monkeypatch.setenv("ITS_API_KEY", "dummy-key")
    s = settings_mod.get_settings()
    assert s.db_path == "x/y.db"
    assert s.its_api_key == "dummy-key"


def test_settings_repr_hides_key(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ITS_API_KEY", "SECRET123")
    assert "SECRET123" not in repr(settings_mod.get_settings())


def test_segments_seed() -> None:
    ids = [s["segment_id"] for s in SEGMENTS]
    assert ids == ["S0", "S1", "S2", "S3", "S4", "S5", "S6"]
    assert [s["is_target"] for s in SEGMENTS] == [0, 1, 1, 1, 1, 1, 1]
    assert [s["seq"] for s in SEGMENTS] == list(range(7))


def test_segment_links_match_segments() -> None:
    import csv
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "config" / "segment_links.csv"
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert {r["segment_id"] for r in rows} == {s["segment_id"] for s in SEGMENTS}
    assert len({r["link_id"] for r in rows}) == len(rows)
    assert all(len(r["link_id"]) == 10 and r["link_id"].isdigit() for r in rows)
    assert all(r["valid_from"].endswith("+09:00") for r in rows)


def test_segment_links_csv_is_build_output() -> None:
    import csv
    from pathlib import Path

    from config.build_segment_links import DST, build

    with Path(DST).open(encoding="utf-8", newline="") as f:
        on_disk = [dict(r) for r in csv.DictReader(f)]
    assert on_disk == [{k: str(v) for k, v in r.items()} for r in build()]


def test_split_links_merged_into_parent() -> None:
    from config.build_segment_links import build

    rows = {r["link_id"]: r for r in build()}
    # 4140114100 + 4140114102(282.3) + 4140114101(11.8) → 576.5m (첫 ITS 실측 역산 576.7m)
    assert rows["4140114100"]["link_length_m"] == "576.5"
    assert "4140114102" not in rows and "4140114101" not in rows


def test_its_id_override_applied() -> None:
    from config.build_segment_links import build

    rows = {r["link_id"]: r for r in build()}
    assert "4140068801" not in rows
    assert rows["4140068800"]["segment_id"] == "S3"
    assert rows["4140068800"]["link_length_m"] == "111.7"
