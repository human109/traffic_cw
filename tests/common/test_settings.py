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
    assert ids == ["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7"]
    assert [s["is_target"] for s in SEGMENTS] == [0, 1, 1, 1, 1, 1, 1, 1]
    assert [s["seq"] for s in SEGMENTS] == list(range(8))
