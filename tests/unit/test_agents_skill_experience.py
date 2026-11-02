"""
تست واحد عامل‌های «استخراج مهارت» و «اعتبارسنجی سوابق کاری» (app/agents) و سیگنال‌های متنی مشترکشان.
"""

import datetime

import pytest

from app.agents.experience_agent import run_experience_agent
from app.agents.skill_agent import run_skill_agent
from app.agents.text_signals import extract_claimed_total_years, extract_skill_year_claims

THIS_YEAR = datetime.date.today().year


def _work(*rows):
    return {"work_experience": [{"company": c, "job_title": t, "duration": d} for c, t, d in rows]}


def _codes(output):
    return [flag.code for flag in output.flags]


# ---------------------------------------------------------------------------
# عامل مهارت ↔ گراف مهارت
# ---------------------------------------------------------------------------
def test_skills_are_matched_to_the_ontology_with_parents_inferred():
    output = run_skill_agent("Built APIs with FastAPI and FastAPI background tasks; Docker for deployment.", None)
    by_name = {item.name: item for item in output.skills}

    assert output.status == "completed"
    assert set(by_name) == {"FastAPI", "Python", "Docker", "DevOps"}
    assert by_name["FastAPI"].core == "Python" and by_name["FastAPI"].evidence_count == 2
    assert by_name["FastAPI"].confidence == 0.7 and not by_name["FastAPI"].inferred
    assert by_name["Python"].inferred and by_name["Python"].evidence_count == 0 and by_name["Python"].confidence == 0.5
    assert by_name["Docker"].category == "DevOps"


def test_skill_output_is_deterministic_and_sorted():
    text = "Kubernetes, React, Python, PostgreSQL"
    first, second = run_skill_agent(text, None), run_skill_agent(text, None)
    assert first == second
    assert [item.name for item in first.skills] == sorted(item.name for item in first.skills)


def test_skill_year_claims_are_attached():
    output = run_skill_agent("Python (8 years), 3 yrs Docker", None)
    claims = {item.name: item.claimed_years for item in output.skills}
    assert claims["Python"] == 8.0 and claims["Docker"] == 3.0 and claims["DevOps"] is None


def test_no_skills_in_unrelated_text():
    assert run_skill_agent("کارشناس حسابداری با تسلط بر اکسل", None).skills == []


# ---------------------------------------------------------------------------
# سیگنال‌های متنی (فارسی و انگلیسی)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "years"),
    [
        ("12+ years of professional experience", 12.0),
        ("experience of 7 years in banking", 7.0),
        ("دارای ۸ سال سابقه در توسعه", 8.0),
        ("سابقه کاری 6 سال", 6.0),
        ("worked 2019-2023", None),
    ],
)
def test_claimed_total_years(text, years):
    assert extract_claimed_total_years(text)[0] == years


def test_skill_claims_do_not_leak_to_the_next_skill():
    claims = extract_skill_year_claims(
        "8 years of Kubernetes, Python (10 years), ۵ سال تجربه در Django and 2 yrs React"
    )
    assert {skill: years for skill, (years, _) in claims.items()} == {
        "Kubernetes": 8.0,
        "Python": 10.0,
        "Django": 5.0,
        "React": 2.0,
    }


# ---------------------------------------------------------------------------
# عامل اعتبارسنجی سوابق: تداخل، تقویم، بزرگ‌نمایی
# ---------------------------------------------------------------------------
def test_overlaps_are_detected_pairwise_and_merged_total_is_net():
    output = run_experience_agent("", _work(("A", "Developer", "2015 - 2019"), ("B", "Developer", "2018 - 2020")))

    assert output.total_experience_years == 5.0  # ۲۰۱۵ تا ۲۰۲۰، نه ۴ + ۲
    assert [(overlap.entries, overlap.years) for overlap in output.overlaps] == [((0, 1), 1.0)]
    assert output.flags == []


def test_shamsi_and_gregorian_periods_are_compared_on_one_calendar():
    # ۱۳۹۵ تا ۱۳۹۸ ≈ ۲۰۱۶ تا ۲۰۱۹؛ با ۲۰۱۸ تا ۲۰۲۰ یک سال تداخل دارد
    output = run_experience_agent("", _work(("A", "Dev", "1395 - 1398"), ("B", "Dev", "2018 - 2020")))

    assert output.entries[0].start_year_gregorian == 2016
    assert [(overlap.entries, overlap.years) for overlap in output.overlaps] == [((0, 1), 1.0)]
    assert output.total_experience_years == 4.0


def test_adjacent_jobs_do_not_overlap():
    output = run_experience_agent("", _work(("A", "Dev", "2015 - 2018"), ("B", "Dev", "2018 - 2021")))
    assert output.overlaps == [] and output.total_experience_years == 6.0


def test_claimed_years_far_above_history_is_an_exaggeration():
    output = run_experience_agent("Engineer with 15+ years of experience", _work(("A", "Engineer", "2019 - 2023")))
    flag = next(flag for flag in output.flags if flag.code == "claimed_years_exceed_history")

    assert flag.severity == "high" and "15" in flag.message and flag.evidence == "15+ years of experience"
    assert output.claimed_total_years == 15.0


def test_small_claim_difference_is_tolerated():
    output = run_experience_agent("5 years of experience", _work(("A", "Engineer", "2019 - 2023")))
    assert "claimed_years_exceed_history" not in _codes(output)


@pytest.mark.parametrize(
    ("title", "flagged"),
    [("Senior Backend Developer", True), ("CTO", True), ("مدیر فنی", True), ("Backend Developer", False)],
)
def test_senior_title_with_short_tenure(title, flagged):
    output = run_experience_agent("", _work(("A", title, f"{THIS_YEAR - 2} - {THIS_YEAR}")))
    assert ("seniority_title_vs_tenure" in _codes(output)) is flagged


def test_more_than_two_concurrent_full_time_roles():
    output = run_experience_agent(
        "", _work(("A", "Dev", "2018 - 2021"), ("B", "Dev", "2019 - 2021"), ("C", "Dev", "2019 - 2020"))
    )
    assert "concurrent_full_time_roles" in _codes(output)


def test_skill_years_longer_than_the_whole_career():
    output = run_experience_agent("Kubernetes (10 years)", _work(("A", "DevOps", "2020 - 2023")))
    flag = next(flag for flag in output.flags if flag.code == "skill_years_exceed_career")
    assert flag.severity == "high" and "Kubernetes" in flag.message


def test_future_and_unparseable_periods_are_invalid():
    output = run_experience_agent("", _work(("A", "Dev", f"{THIS_YEAR + 3} - {THIS_YEAR + 5}"), ("B", "Dev", "نامشخص")))

    assert output.invalid_periods == [0, 1]
    assert _codes(output).count("invalid_period") == 2
    assert output.total_experience_years == 0.0


def test_no_parsed_data_means_empty_but_valid_output():
    output = run_experience_agent("some text", None)
    assert output.status == "completed" and output.entries == [] and output.total_experience_years == 0.0
