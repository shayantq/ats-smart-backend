"""داده‌های ساختگی برای شواهد و تاریخ‌ها؛ هیچ رزومهٔ واقعی در تست نیست."""

from datetime import date

import pytest

from app.core.employment_evidence import extract_employment, analyze_evidence


def document(duration="تیر ۱۴۰۵ تا اکنون", title="کارآموز توسعه بکاند"):
    return f"سوابق کاری\n{title} | Example Labs\n{duration}\nپروژه‌ها\nDeveloper | Other Project\n1400 - 1404"


@pytest.mark.parametrize("duration", ["تیر ۱۴۰۵ تا اکنون", "تیر ١٤٠٥ تا اکنون", "1405/04 تا اکنون", "تا اکنون۱۴۰۵ تیر"])
def test_persian_dates_and_projects(duration):
    entries = extract_employment(document(duration))
    assert len(entries) == 1 and entries[0]["company"] == "Example Labs"
    analyzed, years = analyze_evidence(entries, date(2026, 11, 15))
    assert analyzed[0]["is_valid"] and 0 < years < 1
    assert entries[0]["evidence"]


@pytest.mark.parametrize(
    "duration", ["1406/01 تا اکنون", "1404/13 تا اکنون", "1404 - 1400", "2028 - 2029", "1900 - 2000", "unknown"]
)
def test_invalid_dates_do_not_count(duration):
    analyzed, years = analyze_evidence([dict(duration=duration)], date(2026, 11, 15))
    assert not analyzed[0]["is_valid"] and years == 0


def test_deduplication_preserves_distinct_roles():
    text = document().split("پروژه‌ها")[0]
    entries = extract_employment(text + text + document(title="مهندس نرم افزار"))
    assert len(entries) == 2


def test_overlapping_intervals_do_not_double_count_and_mixed_calendars_convert():
    rows = [dict(duration="1400/01 تا 1402/01"), dict(duration="2021/04 تا 2023/03")]
    _, first = analyze_evidence(rows[:1], date(2026, 11, 15))
    _, union = analyze_evidence(rows, date(2026, 11, 15))
    assert union == first


def test_unknown_days_are_not_invented():
    _, years = analyze_evidence([dict(duration="2020/01 تا 2020/02")], date(2026, 11, 15))
    assert years < 0.01


def test_model_fabrications_are_not_authoritative():
    from app.model_inference.pipeline import map_analysis
    from tests.unit.test_model_inference import response

    prediction = response()
    from app.model_inference.contract import Position

    prediction.analysis.experience.positions = [
        Position(company="Invented Store", job_title="Support", duration="10 years")
    ] * 2
    result = map_analysis(prediction, document(), {}, 1)
    assert len(result.experience.entries) == 1
    assert result.experience.entries[0].company == "Example Labs"
    assert result.experience.entries[0].evidence
    assert result.experience.total_experience_years != 10
