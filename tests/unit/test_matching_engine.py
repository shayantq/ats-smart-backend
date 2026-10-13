"""
تست منطق تجاری موتور نمره‌دهی (Matching Score Engine).

طبق معیار پذیرش تسک: باید تأیید شود که در صورت عدم تطابق مهارت‌های کلیدی،
دقیقاً امتیاز بخش ۵۰ درصدی (سهم مهارت‌های اجباری آگهی) کسر می‌شود.
"""

from app.core.matching_engine import (
    EDUCATION_MATCH_WEIGHT,
    LOCATION_MATCH_WEIGHT,
    SECONDARY_KEYWORDS_WEIGHT,
    SENIORITY_MATCH_WEIGHT,
    SKILL_MATCH_WEIGHT,
    TITLE_MATCH_WEIGHT,
    calculate_matching_score,
)


def test_weights_sum_to_one_hundred():
    """جمع همه‌ی وزن‌های تعریف‌شده باید دقیقاً ۱۰۰ باشد (طبق معیار پذیرش: نمره‌ی نهایی بین ۰ تا ۱۰۰)."""
    total_weight = (
        SKILL_MATCH_WEIGHT
        + TITLE_MATCH_WEIGHT
        + SENIORITY_MATCH_WEIGHT
        + EDUCATION_MATCH_WEIGHT
        + LOCATION_MATCH_WEIGHT
        + SECONDARY_KEYWORDS_WEIGHT
    )
    assert total_weight == 100.0


def test_final_score_is_always_within_zero_to_hundred():
    """خروجی الگوریتم رتبه‌بندی باید همیشه بین ۰ تا ۱۰۰ باشد (معیار پذیرش تسک)."""
    result = calculate_matching_score(
        job_skills_required=["Python"],
        job_title="توسعه‌دهنده بک‌اند",
        job_required_seniority="Senior",
        job_required_education="کارشناسی ارشد",
        job_location="تهران",
        job_description="با Docker و Kubernetes کار خواهید کرد.",
        candidate_skills=[],
        candidate_job_titles=[],
        candidate_total_experience_years=0,
        candidate_education_entries=[],
        candidate_location="اصفهان",
    )
    assert 0.0 <= result["final_score"] <= 100.0


def test_perfect_match_scores_one_hundred():
    """وقتی همه‌چیز کاملاً مطابقت دارد، نمره‌ی نهایی باید ۱۰۰ باشد."""
    result = calculate_matching_score(
        job_skills_required=["Python", "Docker"],
        job_title="توسعه‌دهنده بک‌اند",
        job_required_seniority="Mid-Level",
        job_required_education="کارشناسی",
        job_location="تهران",
        job_description="با FastAPI و PostgreSQL کار خواهید کرد.",
        candidate_skills=["Python", "FastAPI", "Docker", "PostgreSQL", "SQL"],
        candidate_job_titles=["توسعه‌دهنده بک‌اند"],
        candidate_total_experience_years=4.0,
        candidate_education_entries=[{"degree": "کارشناسی", "university": "تهران", "gpa": 17.0}],
        candidate_location="تهران",
    )
    assert result["final_score"] == 100.0


def test_no_required_skill_match_deducts_exactly_fifty_percent():
    """
    معیار پذیرش اصلی این تسک: اگر هیچ‌کدام از مهارت‌های کلیدی/اجباری آگهی در
    رزومه‌ی کارجو پیدا نشوند، سهم ۵۰ درصدی این بخش باید کاملاً صفر شود —
    یعنی حداکثر نمره‌ی ممکن برای این کارجو، ۱۰۰ منهای همان ۵۰ (سهم بخش‌های
    دیگر) خواهد بود.
    """
    result = calculate_matching_score(
        job_skills_required=["Python", "Docker"],
        job_title="توسعه‌دهنده بک‌اند",
        job_required_seniority=None,
        job_required_education=None,
        job_location=None,
        job_description=None,
        candidate_skills=["Photoshop", "Illustrator"],  # کاملاً بی‌ربط به مهارت‌های موردنیاز
        candidate_job_titles=["توسعه‌دهنده بک‌اند"],
        candidate_total_experience_years=4.0,
        candidate_education_entries=[],
        candidate_location=None,
    )

    assert result["breakdown"]["skill_match"] == 0.0
    assert result["matched_required_skills"] == []
    # چون سایر بخش‌ها (عنوان شغلی، ارشدیت، تحصیلات، موقعیت، کلمات ثانویه) در
    # این سناریو کامل محسوب می‌شوند (داده‌ی کافی برای جریمه کردنشان نیست)،
    # نمره‌ی نهایی باید دقیقاً برابر با ۱۰۰ منهای وزن بخش مهارت (۵۰) باشد.
    assert result["final_score"] == 100.0 - SKILL_MATCH_WEIGHT


def test_partial_required_skill_match_gives_proportional_score():
    """اگر فقط نیمی از مهارت‌های اجباری موجود باشند، سهم این بخش باید دقیقاً نصف وزن آن باشد."""
    result = calculate_matching_score(
        job_skills_required=["Python", "Docker"],
        job_title="",
        job_required_seniority=None,
        job_required_education=None,
        job_location=None,
        job_description=None,
        candidate_skills=["Python"],  # فقط یکی از دوتای موردنیاز
        candidate_job_titles=[],
        candidate_total_experience_years=0,
        candidate_education_entries=[],
        candidate_location=None,
    )
    assert result["breakdown"]["skill_match"] == SKILL_MATCH_WEIGHT / 2


def test_sub_skill_matches_via_skill_graph():
    """
    اگر آگهی «Python» بخواهد و کارجو فقط زیرشاخه‌ی آن («FastAPI») را ذکر کرده
    باشد، باز هم باید تطابق شناسایی شود (طبق گراف مهارت).
    """
    result = calculate_matching_score(
        job_skills_required=["Python"],
        job_title="",
        job_required_seniority=None,
        job_required_education=None,
        job_location=None,
        job_description=None,
        candidate_skills=["FastAPI", "Python"],  # خروجی Skill Engine همیشه مهارت اصلی را هم اضافه می‌کند
        candidate_job_titles=[],
        candidate_total_experience_years=0,
        candidate_education_entries=[],
        candidate_location=None,
    )
    assert result["breakdown"]["skill_match"] == SKILL_MATCH_WEIGHT
    assert "Python" in result["matched_required_skills"]


def test_seniority_below_requirement_gives_proportional_score():
    """کارجویی با سابقه‌ی کمتر از حداقل موردنیاز آگهی، باید امتیاز نسبی (نه صفر و نه کامل) بگیرد."""
    result = calculate_matching_score(
        job_skills_required=[],
        job_title="",
        job_required_seniority="Senior",  # حداقل ۵ سال سابقه
        job_required_education=None,
        job_location=None,
        job_description=None,
        candidate_skills=[],
        candidate_job_titles=[],
        candidate_total_experience_years=2.5,  # نصف حداقل موردنیاز
        candidate_education_entries=[],
        candidate_location=None,
    )
    assert result["breakdown"]["seniority_match"] == SENIORITY_MATCH_WEIGHT / 2


def test_seniority_at_or_above_requirement_gives_full_score():
    """کارجویی با سابقه‌ی مساوی یا بیشتر از حداقل موردنیاز، نباید به‌خاطر تجربه‌ی بیشتر جریمه شود."""
    result = calculate_matching_score(
        job_skills_required=[],
        job_title="",
        job_required_seniority="Senior",
        job_required_education=None,
        job_location=None,
        job_description=None,
        candidate_skills=[],
        candidate_job_titles=[],
        candidate_total_experience_years=15.0,  # خیلی بیشتر از حداقل
        candidate_education_entries=[],
        candidate_location=None,
    )
    assert result["breakdown"]["seniority_match"] == SENIORITY_MATCH_WEIGHT
