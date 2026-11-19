import pytest

from common.grades import GRADE_LABEL, grade
from config.settings import Settings

S = Settings()


@pytest.mark.parametrize(
    ("speed", "expected"),
    [(40.0, "free"), (39.9, "slow"), (20.0, "slow"), (19.9, "jam"), (0.5, "jam"), (None, None)],
)
def test_grade_bounds(speed, expected) -> None:
    assert grade(speed, S) == expected


def test_labels() -> None:
    assert GRADE_LABEL == {"free": "원활", "slow": "서행", "jam": "정체"}


def test_nan_is_none() -> None:
    assert grade(float("nan"), S) is None
