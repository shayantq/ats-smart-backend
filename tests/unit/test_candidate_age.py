"""تست واحد محاسبه‌ی سن کارجو (app/core/candidate_utils.py::calculate_candidate_age)."""

from datetime import date

import pytest

from app.core.candidate_utils import calculate_candidate_age

TODAY = date(2026, 10, 9)


@pytest.mark.parametrize(
    ("birth_date", "expected_age"),
    [
        (date(1996, 5, 20), 30),  # تولد امسال گذشته
        (date(1996, 12, 1), 29),  # تولد امسال هنوز نرسیده — یک سال کمتر
        (date(2000, 10, 9), 26),  # دقیقاً امروز تولدش است
        (date(2000, 10, 10), 25),  # فردا تولدش است
        (date(2026, 1, 1), 0),  # نوزاد امسالی — سن صفر معتبر است
        (date(2026, 10, 9), 0),  # امروز به دنیا آمده
    ],
)
def test_calculates_completed_years(birth_date, expected_age):
    assert calculate_candidate_age(birth_date, today=TODAY) == expected_age


def test_leap_day_birthday():
    # متولد ۲۹ فوریه در سال غیرکبیسه، از ۱ مارس یک سال بزرگ‌تر حساب می‌شود
    assert calculate_candidate_age(date(2000, 2, 29), today=date(2025, 2, 28)) == 24
    assert calculate_candidate_age(date(2000, 2, 29), today=date(2025, 3, 1)) == 25


@pytest.mark.parametrize("birth_date", [date(2026, 10, 10), date(2027, 1, 1), date(2100, 6, 15)])
def test_negative_age_raises_value_error(birth_date):
    """تاریخ تولد در آینده یعنی سن منفی — باید ValueError پرتاب شود، نه یک عدد منفی بی‌صدا."""
    with pytest.raises(ValueError, match="منفی"):
        calculate_candidate_age(birth_date, today=TODAY)


def test_defaults_to_current_date():
    assert calculate_candidate_age(date(1990, 1, 1)) >= 36
