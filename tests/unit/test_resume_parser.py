"""تست واحد پارسر رزومه و NER ترکیبی (app/core/resume_parser.py)."""

from app.core.resume_parser import parse_resume_text

SAMPLE_RESUME = """Ali Rezaei
ali.rezaei@example.com
۰۹۱۲۱۲۳۴۵۶۷

تجربه کاری
شرکت نوآوران
توسعه‌دهنده بک‌اند
1397 - 1401

تحصیلات
کارشناسی مهندسی کامپیوتر
دانشگاه تهران
معدل: 17.5
"""


def test_extracts_personal_info_with_persian_digits_normalized():
    info = parse_resume_text(SAMPLE_RESUME).personal_info

    assert info.name == "Ali Rezaei"
    assert info.email == "ali.rezaei@example.com"
    assert info.phone == "09121234567"  # ارقام فارسی به لاتین تبدیل شده‌اند


def test_extracts_work_experience_section():
    experience = parse_resume_text(SAMPLE_RESUME).work_experience

    assert len(experience) == 1
    assert experience[0].company == "نوآوران"
    assert experience[0].job_title == "توسعه‌دهنده بک‌اند"
    assert experience[0].duration == "1397 - 1401"


def test_extracts_education_with_gpa():
    education = parse_resume_text(SAMPLE_RESUME).education

    assert len(education) == 1
    assert education[0].degree == "کارشناسی"
    assert education[0].university == "تهران"
    assert education[0].gpa == 17.5


def test_empty_text_returns_empty_structure():
    parsed = parse_resume_text("")

    assert parsed.work_experience == []
    assert parsed.education == []
    assert parsed.personal_info.email is None
