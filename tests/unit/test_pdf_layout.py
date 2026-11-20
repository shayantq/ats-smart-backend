"""تست هندسه و انتخاب OCR با اسناد ساختگی؛ بدون دادهٔ شخصی."""

import fitz
import pytest

from app.core.pdf_layout import EXTRACTION_VERSION, extract_pdf, word_text
from app.core.text_extraction import extract_raw_text, UnreadableResumeFileError
from app.core.resume_sections import heading


def pdf(pages):
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page()
        for x, y, text in lines:
            page.insert_text((x, y), text, fontsize=11)
    result = doc.tobytes()
    doc.close()
    return result


def fake_ocr(page, clip, deadline):
    return {
        1: [
            dict(text="Scanned", bbox=[40, 60, 95, 75], method="ocr", confidence=90),
            dict(text="content", bbox=[100, 60, 160, 75], method="ocr", confidence=80),
        ]
    }


def test_hybrid_page_does_not_disappear_and_healthy_text_never_ocr(monkeypatch):
    calls = []

    def ocr(page, clip, deadline):
        calls.append(page.number)
        return fake_ocr(page, clip, deadline)

    monkeypatch.setattr("app.core.pdf_layout.ocr_words", ocr)
    result = extract_pdf(pdf([[(30, 60, "Native healthy page")], []]))
    assert calls == [1]
    assert "Native healthy page" in result["raw_text"] and "Scanned content" in result["raw_text"]
    assert result["pages"][1]["blocks"][0]["method"] == "ocr"


def test_ocr_failure_preserves_native_text_and_exposes_partial(monkeypatch):
    def ocr(*args):
        raise RuntimeError("private details")

    monkeypatch.setattr("app.core.pdf_layout.ocr_words", ocr)
    result = extract_pdf(pdf([[(30, 60, "Native healthy page")], []]))
    assert result["status"] == "partial" and "ocr_region_failed" in result["warnings"]
    assert "private" not in str(result)


def test_empty_and_locked_files_are_explicit_failures(monkeypatch):
    monkeypatch.setattr("app.core.pdf_layout.ocr_words", lambda *args: {})
    with pytest.raises(UnreadableResumeFileError):
        extract_raw_text(pdf([[]]), "file.pdf")
    with pytest.raises(UnreadableResumeFileError):
        extract_raw_text(b"corrupt", "file.pdf")
    doc = fitz.open(stream=pdf([[(30, 60, "secret")]]), filetype="pdf")
    locked = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="pass")
    with pytest.raises(UnreadableResumeFileError, match="encrypted_pdf"):
        extract_raw_text(locked, "file.pdf")


def test_columns_are_not_interleaved_and_coordinates_survive():
    content = pdf(
        [
            [
                (40, 60, "EXPERIENCE"),
                (40, 85, "Engineer"),
                (40, 110, "Example Company"),
                (360, 60, "SKILLS"),
                (360, 85, "Python"),
                (360, 110, "Git"),
            ]
        ]
    )
    result = extract_pdf(content)
    text = result["raw_text"]
    assert text.index("Example Company") < text.index("SKILLS")
    page = result["pages"][0]
    assert page["layout"] == "columns"
    for block in page["blocks"]:
        assert block["page"] == 1 and 0 <= block["bbox"][0] < block["bbox"][2] <= page["width"]


def test_duplicate_pages_and_repeated_margins_keep_original_evidence():
    result = extract_pdf(
        pdf(
            [
                [(30, 25, "Synthetic Header"), (30, 90, "First body")],
                [(30, 25, "Synthetic Header"), (30, 90, "Second body")],
                [(30, 25, "Synthetic Header"), (30, 90, "Second body")],
            ]
        )
    )
    assert result["raw_text"].count("Synthetic Header") == 1
    assert result["raw_text"].count("Second body") == 1
    assert result["pages"][2]["duplicate_of"] == 2
    assert result["pages"][2]["blocks"]


def test_word_order_preserves_latin_phrase_in_rtl_line():
    tokens = ["ATS", "Smart", "توسعه‌دهنده", "کارآموز"]
    words = [dict(text=t, bbox=[i * 40, 0, i * 40 + 30, 10]) for i, t in enumerate(tokens)]
    assert word_text(words) == "کارآموز توسعه‌دهنده ATS Smart"


def test_direction_is_detected_after_normalizing_presentation_forms():
    # حروف نمایشی PDF در محدودهٔ اصلی حروف عربی نیستند.
    words = [
        dict(text="\ufedb\ufe8e\ufead\ufbfd", bbox=[0, 0, 30, 10]),
        dict(text="\ufeb3\ufeee\ufe8d\ufe91\ufed6", bbox=[40, 0, 80, 10]),
    ]
    assert word_text(words).startswith("سوابق")


@pytest.mark.parametrize(
    "label,kind",
    [
        ("Professional Experience", "experience"),
        ("فعالیت‌های داوطلبانه", "volunteering"),
        ("Training / Courses", "certifications"),
        ("Selected projects:", "projects"),
    ],
)
def test_section_aliases(label, kind):
    assert heading(label) == kind


def test_wrapped_section_heading_is_connected():
    result = extract_pdf(pdf([[(30, 60, "PROFESSIONAL"), (30, 75, "EXPERIENCE"), (30, 95, "Engineer")]]))
    assert result["pages"][0]["blocks"][0]["section"] == "experience"
    assert result["pages"][0]["blocks"][0]["joined_line_ids"]


def test_volunteering_and_projects_do_not_leak_into_employment():
    from app.core.resume_parser import _split_into_sections

    sections = _split_into_sections(
        "Professional Experience\nEngineer\nVOLUNTEERING\nVolunteer Developer\nPROJECTS\nProject Developer"
    )
    assert "Volunteer" not in sections["experience"] and "Project" not in sections["experience"]
    assert "Volunteer" in sections["volunteering"] and "Project" in sections["projects"]


def test_native_table_cells_have_geometry():
    doc = fitz.open()
    p = doc.new_page()
    for x in (40, 250, 500):
        p.draw_line((x, 40), (x, 160))
    for y in (40, 80, 120, 160):
        p.draw_line((40, y), (500, y))
    for x, y, s in [(50, 65, "Role"), (260, 65, "Date"), (50, 105, "Engineer"), (260, 105, "2020 - 2022")]:
        p.insert_text((x, y), s)
    result = extract_pdf(doc.tobytes())
    assert result["pages"][0]["tables"]
    assert all(len(cell) == 4 for cell in result["pages"][0]["tables"][0]["cells"] if cell)


async def test_layout_is_persisted_before_parser_or_model_failure(monkeypatch):
    from app.model_inference import pipeline

    stored = []

    async def persist(text, parsed, stage, metrics):
        stored.append((text, parsed, stage))

    def failed_parser(text, **kwargs):
        raise ValueError("synthetic parser failure")

    monkeypatch.setattr(pipeline, "parse_resume_text", failed_parser)
    with pytest.raises(ValueError):
        await pipeline.run_model_pipeline(pdf([[(30, 60, "Synthetic healthy text")]]), "test.pdf", {}, persist=persist)
    assert stored[0][2] == "parsing"
    assert stored[0][1]["_extraction"]["pages"][0]["blocks"]
    assert stored[0][1]["_extraction"]["version"] == EXTRACTION_VERSION


def test_repeated_record_title_at_top_preserves_both_dated_records():
    with fitz.open() as document:
        for year in (2021, 2023):
            page = document.new_page()
            page.insert_text((50, 24), "Instructor", fontsize=13, fontname="hebo")
            page.insert_text((50, 49), "Synthetic Academy", fontsize=10)
            page.insert_text((50, 70), f"January {year}", fontsize=8)
        result = extract_pdf(document.tobytes())
    assert result["raw_text"].count("Instructor") == 2
    assert all(page["blocks"][0]["native_style"]["bold"] for page in result["pages"])
