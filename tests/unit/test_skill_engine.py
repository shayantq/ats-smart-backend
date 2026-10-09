"""
تست واحد موتور مهارت: گراف مهارت (skill_graph.py) و تحلیل‌گر سوابق کاری (experience_analyzer.py).
"""

from app.core.experience_analyzer import analyze_work_experience
from app.core.skill_engine import run_skill_engine
from app.core.skill_graph import get_core_skill, match_skills


# ---------------------------------------------------------------------------
# گراف مهارت
# ---------------------------------------------------------------------------
def test_sub_skill_also_adds_its_parent_skill():
    assert match_skills("I build APIs with FastAPI") == ["FastAPI", "Python"]


def test_matching_respects_word_boundaries():
    # «java» نباید داخل «javascript» تشخیص داده شود
    assert match_skills("Senior JavaScript developer") == ["JavaScript"]
    assert "Java" in match_skills("Java and Spring Boot")


def test_matching_is_case_insensitive_and_deterministic():
    assert match_skills("docker, KUBERNETES and postgresql") == ["DevOps", "Docker", "Kubernetes", "PostgreSQL", "SQL"]


def test_text_without_known_skills():
    assert match_skills("") == []
    assert match_skills("Excellent communication") == []


def test_get_core_skill():
    assert get_core_skill("Django") == "Python"
    assert get_core_skill("python") == "Python"
    assert get_core_skill("Photoshop") == "Photoshop"  # خارج از گراف → خودِ ورودی


# ---------------------------------------------------------------------------
# تحلیل‌گر سوابق کاری
# ---------------------------------------------------------------------------
def _years(*durations: str) -> float:
    return analyze_work_experience([{"duration": duration} for duration in durations])["total_experience_years"]


def test_overlapping_jobs_are_not_counted_twice():
    # ۱۳۹۶–۱۳۹۹ و ۱۳۹۸–۱۴۰۱ هم‌پوشانی دارند → ۵ سال خالص، نه ۶
    assert _years("1396 - 1399", "1398 - 1401") == 5.0


def test_separate_periods_are_summed():
    assert _years("2010 - 2012", "2015 - 2018") == 5.0


def test_overlapping_gregorian_periods_are_merged():
    assert _years("2016 - 2018", "2017 - 2020") == 4.0


def test_invalid_periods_are_flagged_and_excluded():
    result = analyze_work_experience(
        [
            {"company": "A", "duration": "1396 - 1399"},
            {"company": "Fake", "duration": "1400 - 1395"},  # پایان قبل از شروع
            {"company": "Future", "duration": "1410 - 1412"},  # در آینده
        ]
    )

    assert result["total_experience_years"] == 3.0
    flags = {entry["company"]: (entry["is_valid"], entry["flag_reason"]) for entry in result["entries"]}
    assert flags["A"] == (True, None)
    assert flags["Fake"][0] is False and "قبل از تاریخ شروع" in flags["Fake"][1]
    assert flags["Future"][0] is False and "آینده" in flags["Future"][1]


def test_missing_duration_does_not_crash():
    assert _years() == 0.0
    assert analyze_work_experience([{"company": "X", "duration": None}])["total_experience_years"] == 0.0


def test_run_skill_engine_combines_skills_and_experience():
    result = run_skill_engine("Python and Django developer", [{"duration": "2015 - 2018"}])

    assert result["skills"] == ["Django", "Python"]
    assert result["total_experience_years"] == 3.0
    assert len(result["experience_entries"]) == 1
