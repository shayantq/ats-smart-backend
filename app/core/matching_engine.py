"""
موتور نمره‌دهی و رتبه‌بندی رزومه (Matching Score Engine) — مرحله‌ی چهارم و
نهایی خط لوله‌ی هوش مصنوعی. رزومه‌ی ساختاریافته‌ی کارجو (خروجی مراحل NER و
Skill Engine) را در برابر نیازمندی‌های آگهی شغلی قرار می‌دهد و یک نمره‌ی
نهایی بین ۰ تا ۱۰۰ محاسبه می‌کند.

وزن‌دهی طبق معیار پذیرش تسک:
    ۵۰٪  → تطابق مهارت‌های کلیدی/اجباری آگهی
    ۳۰٪  → تطابق عنوان شغلی + سطح ارشدیت (سال‌های سابقه)
    ۲۰٪  → فاکتورهای تکمیلی (تحصیلات، موقعیت مکانی، کلمات کلیدی ثانویه)

⚠️ تصمیم مهندسی مستند: تقسیم داخلی وزن ۳۰٪ (بین «تطابق عنوان شغلی» و «تطابق
ارشدیت») و وزن ۲۰٪ (بین «تحصیلات»، «موقعیت مکانی» و «کلمات کلیدی ثانویه») در
معیار پذیرش تسک به‌صورت عددی مشخص نشده بود؛ تقسیم‌های زیر (ثابت‌های وزن) یک
انتخاب طراحی صریح و به‌راحتی قابل‌تغییر است، نه یک فرض پنهان.
"""

import re

from app.core.skill_graph import get_core_skill, match_skills

# ---- وزن‌های اصلی طبق معیار پذیرش تسک ----
SKILL_MATCH_WEIGHT = 50.0
TITLE_MATCH_WEIGHT = 15.0  # نیمی از وزن ۳۰٪ («تطابق عنوان شغلی»)
SENIORITY_MATCH_WEIGHT = 15.0  # نیمی دیگر از وزن ۳۰٪ («تطابق ارشدیت/سابقه»)
EDUCATION_MATCH_WEIGHT = 8.0  # از وزن ۲۰٪ فاکتورهای تکمیلی
LOCATION_MATCH_WEIGHT = 8.0  # از وزن ۲۰٪ فاکتورهای تکمیلی
SECONDARY_KEYWORDS_WEIGHT = 4.0  # از وزن ۲۰٪ فاکتورهای تکمیلی
# جمع کل = 50 + 15 + 15 + 8 + 8 + 4 = 100

_SENIORITY_YEAR_RANGES: dict[str, tuple[float, float | None]] = {
    "junior": (0.0, 2.0),
    "mid-level": (2.0, 5.0),
    "mid": (2.0, 5.0),
    "senior": (5.0, 10.0),
    "lead": (8.0, None),
    "principal": (10.0, None),
}

_EDUCATION_LEVEL_RANKS: dict[str, int] = {
    "دیپلم": 1,
    "diploma": 1,
    "کاردانی": 2,
    "associate": 2,
    "کارشناسی": 3,
    "bachelor": 3,
    "b.sc": 3,
    "کارشناسی ارشد": 4,
    "master": 4,
    "m.sc": 4,
    "mba": 4,
    "دکتری": 5,
    "phd": 5,
    "ph.d": 5,
}

_STOPWORDS = {"و", "در", "برای", "با", "the", "a", "an", "of", "and", "for", "to"}


def calculate_matching_score(
    *,
    job_skills_required: list[str] | None,
    job_title: str,
    job_required_seniority: str | None,
    job_required_education: str | None,
    job_location: str | None,
    job_description: str | None,
    candidate_skills: list[str] | None,
    candidate_job_titles: list[str] | None,
    candidate_total_experience_years: float,
    candidate_education_entries: list[dict] | None,
    candidate_location: str | None,
) -> dict:
    """
    نقطه‌ی ورود اصلی موتور. تمام سیگنال‌های لازم (طرف آگهی + طرف رزومه) را
    می‌گیرد و نمره‌ی نهایی (دقیقاً بین ۰ تا ۱۰۰، طبق معیار پذیرش تسک) را به
    همراه ریزنمرات هر بخش (برای شفافیت و اشکال‌زدایی، نه ذخیره‌سازی اجباری)
    برمی‌گرداند.
    """
    skill_score, matched_skills = _calculate_skill_match_score(
        job_skills_required or [], candidate_skills or []
    )
    title_score = _calculate_title_match_score(job_title, candidate_job_titles or [])
    seniority_score = _calculate_seniority_match_score(job_required_seniority, candidate_total_experience_years)
    education_score = _calculate_education_match_score(job_required_education, candidate_education_entries or [])
    location_score = _calculate_location_match_score(job_location, candidate_location)
    secondary_score = _calculate_secondary_keywords_score(job_description, candidate_skills or [])

    total_score = skill_score + title_score + seniority_score + education_score + location_score + secondary_score

    # اطمینان نهایی از محدوده‌ی دقیق ۰ تا ۱۰۰ (طبق معیار پذیرش تسک) — جمع چند
    # مؤلفه‌ی اعشاری به‌ندرت ممکن است یک خطای گرد کردن بسیار کوچک بسازد
    final_score = max(0.0, min(100.0, round(total_score, 2)))

    return {
        "final_score": final_score,
        "breakdown": {
            "skill_match": round(skill_score, 2),
            "title_match": round(title_score, 2),
            "seniority_match": round(seniority_score, 2),
            "education_match": round(education_score, 2),
            "location_match": round(location_score, 2),
            "secondary_keywords_match": round(secondary_score, 2),
        },
        "matched_required_skills": matched_skills,
    }


# ---------------------------------------------------------------------------
# بخش ۱ (وزن ۵۰٪): تطابق مهارت‌های کلیدی/اجباری آگهی
# ---------------------------------------------------------------------------
def _calculate_skill_match_score(required_skills: list[str], candidate_skills: list[str]) -> tuple[float, list[str]]:
    """
    برای هر مهارت اجباری آگهی، هم خودِ نام دقیق و هم مهارت اصلی/گره والدش (طبق
    گراف مهارت) در لیست مهارت‌های کارجو جست‌وجو می‌شود — یعنی اگر آگهی
    «Python» بخواهد و کارجو فقط «FastAPI» را ذکر کرده باشد، باز هم تطابق
    شناسایی می‌شود (چون خروجی Skill Engine از قبل «Python» را هم به لیست
    مهارت‌های کارجو اضافه کرده — بنگرید app/core/skill_engine.py).

    اگر آگهی هیچ مهارت اجباری‌ای نداشته باشد، این بخش کامل (بدون جریمه) در
    نظر گرفته می‌شود چون چیزی برای تطبیق وجود ندارد.
    """
    if not required_skills:
        return SKILL_MATCH_WEIGHT, []

    normalized_candidate_skills = {skill.lower() for skill in candidate_skills}

    matched_skills: list[str] = []
    for required_skill in required_skills:
        core_skill = get_core_skill(required_skill)
        if required_skill.lower() in normalized_candidate_skills or core_skill.lower() in normalized_candidate_skills:
            matched_skills.append(required_skill)

    match_ratio = len(matched_skills) / len(required_skills)
    return match_ratio * SKILL_MATCH_WEIGHT, matched_skills


# ---------------------------------------------------------------------------
# بخش ۲ (وزن ۳۰٪): تطابق عنوان شغلی + سطح ارشدیت
# ---------------------------------------------------------------------------
def _extract_significant_words(text: str) -> set[str]:
    words = re.findall(r"[\w\u0600-\u06FF]+", text.lower())
    return {word for word in words if word not in _STOPWORDS and len(word) > 1}


def _calculate_title_match_score(job_title: str, candidate_job_titles: list[str]) -> float:
    """
    عنوان آگهی و هر یک از عناوین شغلی قبلی کارجو (استخراج‌شده در مرحله‌ی NER)
    به مجموعه‌ی کلمات معنادار تبدیل می‌شوند؛ بیشترین نسبت همپوشانی (Overlap
    Ratio) بین آن‌ها به‌عنوان امتیاز این بخش در نظر گرفته می‌شود.
    """
    if not candidate_job_titles:
        return 0.0

    job_title_words = _extract_significant_words(job_title)
    if not job_title_words:
        return TITLE_MATCH_WEIGHT  # عنوان آگهی کلمه‌ی معناداری نداشت -> نمی‌توان قضاوت کرد، امتیاز کامل

    best_overlap_ratio = 0.0
    for candidate_title in candidate_job_titles:
        if not candidate_title:
            continue
        candidate_title_words = _extract_significant_words(candidate_title)
        if not candidate_title_words:
            continue
        overlap_ratio = len(job_title_words & candidate_title_words) / len(job_title_words)
        best_overlap_ratio = max(best_overlap_ratio, overlap_ratio)

    return best_overlap_ratio * TITLE_MATCH_WEIGHT


def _calculate_seniority_match_score(required_seniority: str | None, total_experience_years: float) -> float:
    """
    اگر مجموع سال‌های سابقه‌ی خالص کارجو (خروجی experience_analyzer، بعد از
    کسر تداخل‌های زمانی) حداقل به اندازه‌ی آستانه‌ی سطح ارشدیت موردنیاز آگهی
    باشد، امتیاز کامل داده می‌شود؛ در غیر این صورت، امتیاز متناسب با نسبت
    سابقه‌ی فعلی به حداقل موردنیاز کاهش می‌یابد (بیشتر بودن سابقه جریمه نمی‌شود).
    """
    if not required_seniority:
        return SENIORITY_MATCH_WEIGHT

    year_range = _SENIORITY_YEAR_RANGES.get(required_seniority.strip().lower())
    if year_range is None:
        return SENIORITY_MATCH_WEIGHT  # سطح ارشدیت ناشناخته -> نمی‌توان قضاوت کرد، امتیاز کامل

    min_years, _max_years = year_range

    if min_years <= 0 or total_experience_years >= min_years:
        return SENIORITY_MATCH_WEIGHT

    ratio = max(0.0, total_experience_years / min_years)
    return ratio * SENIORITY_MATCH_WEIGHT


# ---------------------------------------------------------------------------
# بخش ۳ (وزن ۲۰٪): فاکتورهای تکمیلی — تحصیلات، موقعیت مکانی، کلمات کلیدی ثانویه
# ---------------------------------------------------------------------------
def _highest_education_rank(education_entries: list[dict]) -> int:
    best_rank = 0
    for entry in education_entries:
        degree = (entry.get("degree") or "").strip().lower()
        best_rank = max(best_rank, _EDUCATION_LEVEL_RANKS.get(degree, 0))
    return best_rank


def _calculate_education_match_score(required_education: str | None, education_entries: list[dict]) -> float:
    if not required_education:
        return EDUCATION_MATCH_WEIGHT

    required_rank = _EDUCATION_LEVEL_RANKS.get(required_education.strip().lower())
    if required_rank is None:
        return EDUCATION_MATCH_WEIGHT

    candidate_rank = _highest_education_rank(education_entries)
    if candidate_rank == 0:
        return 0.0

    if candidate_rank >= required_rank:
        return EDUCATION_MATCH_WEIGHT

    return (candidate_rank / required_rank) * EDUCATION_MATCH_WEIGHT


def _calculate_location_match_score(job_location: str | None, candidate_location: str | None) -> float:
    """
    اگر یکی از دو طرف موقعیت مکانی ثبت‌نشده باشد، به نفع کارجو امتیاز کامل
    داده می‌شود (بی‌طرفانه — نبود داده نباید جریمه شود، چون فیلد location
    کارجو تازه اضافه شده و هنوز همه پر نکرده‌اند).
    """
    if not job_location or not candidate_location:
        return LOCATION_MATCH_WEIGHT

    normalized_job_location = job_location.strip().lower()
    normalized_candidate_location = candidate_location.strip().lower()

    if normalized_job_location == normalized_candidate_location:
        return LOCATION_MATCH_WEIGHT

    if normalized_job_location in normalized_candidate_location or normalized_candidate_location in normalized_job_location:
        return LOCATION_MATCH_WEIGHT * 0.7  # تطابق جزئی، مثلاً «تهران» در برابر «تهران، ایران»

    return 0.0


def _calculate_secondary_keywords_score(job_description: str | None, candidate_skills: list[str]) -> float:
    """
    توضیحات آگهی برای «مهارت‌های ثانویه» (مهارت‌هایی که در فهرست اجباری
    skills_required نیستند ولی در متن آگهی ذکر شده‌اند) اسکن می‌شود و با
    مهارت‌های کارجو مقایسه می‌شود.
    """
    if not job_description:
        return SECONDARY_KEYWORDS_WEIGHT

    description_skills = set(match_skills(job_description))
    if not description_skills:
        return SECONDARY_KEYWORDS_WEIGHT

    normalized_candidate_skills = {skill.lower() for skill in candidate_skills}
    matched = [skill for skill in description_skills if skill.lower() in normalized_candidate_skills]

    match_ratio = len(matched) / len(description_skills)
    return match_ratio * SECONDARY_KEYWORDS_WEIGHT
