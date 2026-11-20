"""مرجع‌ها همگی ساختگی‌اند؛ هیچ فایل شخصی وارد تست نشده است."""

from datetime import date
import pytest

from app.core.structured_resume import build_structured, find_date, legacy_work
from app.core.resume_dates import date_range, endpoint

NOW = date(2026, 11, 16)
ENGLISH = """MIRA HART
Junior Software Engineer | Python
mira@example.invalid
+1-(234)-555-1234
Harbor City, CA
SUMMARY
Software development for public services.
EXPERIENCE
Junior Software Engineer 01/2025 - Present
Harbor Systems
Harbor City, CA
• Developed a service with 20% faster responses.
Software Engineering Intern 06/2024 - 12/2024
Maple Innovations Corp
VOLUNTEERING
Volunteer Software
Developer
Civic Code Group
01/2024 - 04/2025
PROJECTS
Atlas Tool | Internal reporting
EDUCATION
Bachelor of Science in Computer Science
Synthetic University
01/2019 - 01/2022
TRAINING / COURSES
Python Programming
Certification
Synthetic Academy, 2023
Expires: 01/2025
LANGUAGES
English Native
Spanish Advanced
"""


def test_decorated_teaching_section_preserves_evidence_without_counting_employment():
    from app.core.structured_resume import build_structured

    parsed = build_structured(
        "\uf0b7 سوابق تدریس\nمدرس دوره داده\nآموزشگاه آزمایشی\n۱۴۰۱ تا ۱۴۰۲\nمخاطبان: گروه آزمایشی\n"
        "\uf0b7 تدریس دوره نرم افزار\nدانشگاه نمونه\nتحصیلات\n۱۴۰۳ تا ۱۴۰۴"
    )
    records = parsed["activities"]
    assert [record["kind"] for record in records] == ["teaching", "teaching"]
    assert records[0]["dates"]["status"] == "valid"
    assert records[0]["fields"]["company"]["value"] == "آموزشگاه آزمایشی"
    assert records[0]["fields"]["audience"]["value"] == "گروه آزمایشی"
    assert records[1]["dates"]["status"] == "unknown"


def test_english_records_inline_dates_and_activity_isolation():
    s = build_structured(ENGLISH, reference=NOW)
    work = [r for r in s["activities"] if r["kind"] in {"employment", "internship"}]
    assert len(work) == 2
    assert work[0]["fields"]["company"]["value"] == "Harbor Systems"
    assert work[1]["kind"] == "internship"
    assert work[0]["dates"]["ongoing"]
    assert len([r for r in s["activities"] if r["kind"] == "volunteering"]) == 1
    assert len([r for r in s["activities"] if r["kind"] == "project"]) == 1
    assert len(legacy_work(ENGLISH, reference=NOW)) == 2
    assert work[0]["claims"][0]["status"] == "attributed"
    assert s["identity"]["name"]["value"] == "MIRA HART"
    assert len(s["contacts"]) == 2 and s["identity"]["location"]["value"] == "Harbor City, CA"


def test_qualifications_and_self_reported_languages():
    s = build_structured(ENGLISH, reference=NOW)
    assert s["education"][0]["fields"]["institution"]["value"] == "Synthetic University"
    assert len(s["certifications"]) == 1
    assert s["certifications"][0]["fields"]["title"]["value"] == "Python Programming Certification"
    assert s["certifications"][0]["expiry_status"] == "expired_claim"
    assert s["languages"][0]["fields"]["level"]["status"] == "attributed"
    assert s["certifications"][0]["verification"] == "not_independently_verified"


@pytest.mark.parametrize(
    "value,precision",
    [
        ("01/2025 - Present", "month"),
        ("June 2024 - December 2024", "month"),
        ("1403/01/01 تا 1403/06/31", "day"),
        ("31/01/2024 - 28/02/2024", "day"),
        ("2020 - 2022", "year"),
        ("تیر ۱۴۰۵ تا اکنون", "month"),
    ],
)
def test_date_precision_is_preserved(value, precision):
    r = date_range(value, NOW)
    assert r["status"] == "valid"
    assert r["start"]["precision"] == precision
    if precision != "day":
        assert r["start"]["earliest"] != r["start"]["latest"]


def test_ambiguous_and_invalid_dates_do_not_become_facts():
    with pytest.raises(ValueError):
        endpoint("03/04/2024", NOW)
    for text in ["02/2027 - Present", "2025 - 2022", "2024/02/31 - 2025/01/01", "unknown"]:
        assert date_range(text, NOW)["status"] != "valid"


def test_displaced_pdf_year_is_repaired_without_fabricating_period():
    value = build_structured("سوابق کاری\nکارآموز توسعه | Example Labs\nتیر تا اکنون۱۴۰۵", reference=NOW)
    record = value["activities"][0]
    assert record["dates"]["status"] == "valid"
    assert record["dates"]["start"]["year"] == 1405
    assert record["dates"]["start"]["precision"] == "month"
    assert record["dates"]["ongoing"]
    assert record["kind"] == "internship"


def test_presentation_form_letters_do_not_turn_internship_into_employment():
    value = build_structured("سوابق کاری\nکﺎرﺁموز توسعه | Example Labs\nتیر ۱۴۰۵ تا اکنون", reference=NOW)
    assert value["activities"][0]["kind"] == "internship"


def test_unknown_dates_preserve_role_and_unknown_employer_is_not_filled_by_model():
    s = build_structured("EXPERIENCE\nSoftware Engineer\n• Built services.", reference=NOW)
    assert len(s["activities"]) == 1
    r = s["activities"][0]
    assert r["fields"]["company"]["value"] is None
    assert r["fields"]["duration"]["status"] == "missing"
    assert s["totals"]["total_work"]["max_years"] == 0


def test_duplicates_distinct_roles_and_overlap_union():
    text = (
        "EXPERIENCE\nEngineer | Maple Labs\n2020/01/01 - 2022/01/01\n"
        "Manager | Maple Labs\n2021/01/01 - 2023/01/01\n"
        "Engineer | Maple Labs\n2020/01/01 - 2022/01/01"
    )
    s = build_structured(text, reference=NOW)
    assert len(s["activities"]) == 2
    assert 2.99 < s["totals"]["total_work"]["min_years"] < 3.01
    assert s["overlaps"][0]["status"] == "source_confirmed"


def test_contacts_and_multiple_people_are_not_account_updates():
    s = build_structured(
        "JANE DOE\nJOHN ROE\nhelp@example.invalid\nhttps://github.com/example\nSUMMARY\nProfile.", reference=NOW
    )
    assert s["identity"]["name"]["value"] is None
    assert s["identity"]["name"]["status"] == "ambiguous"
    assert s["contacts"][0]["status"] == "ambiguous"
    assert s["links"][0]["reason"] == "link_not_fetched_or_verified"


def test_evidence_points_to_original_block_and_excluded_footer_is_not_a_source():
    text = "MIRA HART\nEXPERIENCE\nEngineer | Harbor Systems\n2024 - 2025"
    layout = {
        "pages": [
            {
                "number": 1,
                "blocks": [
                    {"id": "b1", "text": "Engineer | Harbor Systems", "bbox": [1, 2, 3, 4]},
                    {
                        "id": "footer",
                        "text": "Harbor Systems",
                        "bbox": [0, 0, 1, 1],
                        "excluded_reason": "generator_footer",
                    },
                ],
            }
        ]
    }
    s = build_structured(text, layout, NOW)
    e = s["activities"][0]["fields"]["company"]["evidence"]
    assert e[0]["block_id"] == "b1" and e[0]["page"] == 1
    assert all(ref["block_id"] != "footer" for ref in e)


def test_employer_before_title_is_part_of_field_evidence():
    text = "EXPERIENCE\nMaple Labs\nSoftware Engineer\n2021 - 2024"
    s = build_structured(text, reference=NOW)
    f = s["activities"][0]["fields"]["company"]
    assert f["value"] == "Maple Labs"
    assert any("Maple Labs" in ref["text"] for ref in f["evidence"])


def test_project_title_is_not_replaced_by_role_in_description():
    text = "PROJECTS\nAtlas Tool | Backend Developer\nPython tooling\n• Built a report."
    s = build_structured(text, reference=NOW)
    assert len(s["activities"]) == 1
    f = s["activities"][0]["fields"]
    assert f["project_name"]["value"] == "Atlas Tool"
    assert f["company"]["value"] is None


def test_parser_does_not_fall_back_to_unsupported_work_or_generic_email():
    from app.core.resume_parser import parse_resume_text

    parsed = parse_resume_text("JANE DOE\nhelp@example.invalid\nEXPERIENCE\nUnclear record", reference=NOW)
    assert parsed.work_experience == []
    assert parsed.personal_info.email is None
    assert "employment_section_without_supported_records" in parsed.structured.warnings


def test_jalali_conversion_known_date_and_disjoint_union_are_exact():
    value = date_range("1403/01/01 تا 1403/01/02", NOW)
    assert value["start"]["earliest"] == "2024-03-20"
    assert value["end"]["earliest"] == "2024-03-21"
    s = build_structured(
        "EXPERIENCE\nEngineer | Maple Labs\n2020/01/01 - 2021/01/01\n"
        "Manager | Harbor Systems\n2023/01/01 - 2024/01/01",
        reference=NOW,
    )
    assert 1.99 < s["totals"]["total_work"]["min_years"] < 2.01
    assert s["gaps"][0]["interpretation"] == "resume_may_be_incomplete"


def test_contract_rejects_value_without_evidence():
    from pydantic import ValidationError
    from app.schemas.structured_resume import Fact

    with pytest.raises(ValidationError, match="fact_requires_evidence"):
        Fact(value="Unsupported company", status="extracted")


def test_employer_and_city_on_same_line_remain_distinct():
    s = build_structured("EXPERIENCE\nSoftware Engineer 01/2025 - Present\nHarbor Systems Austin, TX", reference=NOW)
    f = s["activities"][0]["fields"]
    assert f["company"]["value"] == "Harbor Systems"
    assert f["location"]["value"] == "Austin, TX"


def test_rtl_internship_marker_after_separator_belongs_to_role():
    s = build_structured("سوابق کاری\nتوسعه بک‌اند |کارآموز Maple Labs\nتیر تا اکنون۱۴۰۵", reference=NOW)
    r = s["activities"][0]
    assert r["kind"] == "internship"
    assert r["fields"]["company"]["value"] == "Maple Labs"
    assert "کارآموز" in r["fields"]["job_title"]["value"]


def test_header_location_separators_and_wrapped_languages():
    s = build_structured(
        "MIRA HART\nHarbor City, Iran |\nLANGUAGES\nPersian Native\nEnglish\nIntermediate", reference=NOW
    )
    assert s["identity"]["location"]["value"] == "Harbor City, Iran"
    assert len(s["languages"]) == 2
    assert s["languages"][1]["fields"]["language"]["value"] == "English"
    assert s["languages"][1]["fields"]["level"]["value"] == "Intermediate"


def test_three_inline_languages_and_following_links_are_not_dropped_or_merged():
    s = build_structured(
        "MIRA HART\nHarbor City, Iran |\nLANGUAGES\n"
        "Persian: Native | English: Upper-intermediate | German: Advanced\n"
        "SELECTED LINKS\nGitHub profile: github.com/example\n",
        reference=NOW,
    )
    assert len(s["languages"]) == 3
    assert [x["fields"]["language"]["value"] for x in s["languages"]] == ["Persian", "English", "German"]
    assert s["languages"][1]["fields"]["level"]["value"] == "Upper-intermediate"


def test_decorated_headings_keep_courses_and_memberships_out_of_work_history():
    doc = build_structured(
        "\uf0b7 سوابق کاری\nمهندس نرم‌افزار\nشرکت آزمایشی\n۱۴۰۰ تا ۱۴۰۲\n"
        "دوره‌ها و گواهینامه‌ها \uf0b7\nدوره طراحی نرم‌افزار\nآموزشگاه نمونه\n"
        "| تحصیلات \u200f\nکارشناسی علوم رایانه\nدانشگاه نمونه\n"
        "\uf0b7 زبان‌ها\nEnglish Advanced\n"
        "\uf0b7 افتخارات\nجایزه آزمایشی\n\uf0b7 عضویت‌ها\nانجمن نمونه\n",
        reference=NOW,
    )
    assert [record["kind"] for record in doc["activities"]] == ["employment"]
    assert doc["activities"][0]["dates"]["status"] == "valid"
    assert len(doc["certifications"]) == len(doc["education"]) == len(doc["languages"]) == len(doc["awards"]) == 1
    assert doc["awards"][0]["fields"]["title"]["value"] == "جایزه آزمایشی"


def test_teaching_event_date_is_kept_without_inventing_a_duration():
    document = build_structured(
        "سوابق تدریس\nمدرس دوره آزمایشی\nآموزشگاه نمونه\nاردیبهشت‌ماه ۱۴۰۳\n"
        "تدریس درس نمونه\nتوضیح کلاس در سال ۱۴۰۰\n"
        "مدرس برنامه آزمایشی\nتاریخ: ۱۴۹۰\n",
        reference=NOW,
    )
    first, second, third = document["activities"]
    evidence = first["fields"]["date"]
    assert evidence["value"] == evidence["evidence"][0]["text"] == "اردیبهشت‌ماه ۱۴۰۳"
    assert first["dates"]["status"] == "unknown"
    assert "date" not in second["fields"] and "date" not in third["fields"]
    assert document["totals"]["total_work"]["max_years"] == 0


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("شهریور ۱۴۰۴ اکنون \uf02e", "شهریور 1404 تا اکنون"),
        ("اردیبهشت لغایت خرداد۱۴۰۱ ۱۴۰۲", "اردیبهشت 1401 تا خرداد 1402"),
        ("مهر ماه تا آذر ۱۴۰۲", "مهر 1402 تا آذر 1402"),
    ],
)
def test_rtl_calendar_layout_preserves_real_endpoints(line, expected):
    interval = find_date(line)
    assert interval and interval.group() == expected
    assert date_range(interval.group(), NOW)["status"] == "valid"
