"""تست‌های نرمال‌سازی متن و ناشناس‌سازی دیتاست (app/datasets/finetune/text_clean.py و anonymize.py) — داده‌ی ساختگی."""

import pytest

from app.datasets.finetune.anonymize import Identity, Redactor, identity_hashes, redact_patterns
from app.datasets.finetune.text_clean import fingerprint_text, has_mojibake, normalize_text
from tests.finetune_helpers import SAMPLE_IDENTITY, SAMPLE_RESUME

ZWNJ = "\u200c"


# ---------------------------------------------------------------------------
# نرمال‌سازی
# ---------------------------------------------------------------------------
def test_arabic_letters_and_digits_become_persian_letters_and_latin_digits():
    assert normalize_text("علي كريمي ۱۴۰۲ و ٢٠٢٣") == "علی کریمی 1402 و 2023"


def test_zwnj_is_kept_but_other_invisible_and_broken_chars_are_removed():
    text = f"می{ZWNJ}خواهم\u200b \u200e\ufeffسلام\ufffd\x07\x00 دنیا"
    assert normalize_text(text) == f"می{ZWNJ}خواهم سلام دنیا"


def test_whitespace_is_collapsed_and_blank_lines_limited():
    assert normalize_text("  الف\t\tب  \n\n\n\n  ج  ") == "الف ب\n\nج"


def test_latin1_mojibake_is_repaired_segment_by_segment():
    original = "برنامه‌نویس بک‌اند — Python"
    broken = original.encode("utf-8").decode("latin-1")
    assert has_mojibake(broken)
    assert normalize_text(broken) == original


def test_cp1252_mojibake_with_lost_bytes_stays_detectable():
    broken = "فرهاد فناوری".encode("utf-8").decode("cp1252", errors="ignore")
    assert has_mojibake(normalize_text(broken))


def test_normal_persian_text_is_not_mojibake():
    assert not has_mojibake("«سلام» — کار تیمی، 1402")


def test_fingerprint_ignores_digits_spacing_case_and_punctuation():
    assert fingerprint_text("Python 5 سال، Docker!") == fingerprint_text("python   7 سال - docker")


# ---------------------------------------------------------------------------
# ناشناس‌سازی
# ---------------------------------------------------------------------------
@pytest.fixture
def redacted() -> str:
    return Redactor.for_identity(SAMPLE_IDENTITY).resume_text(normalize_text(SAMPLE_RESUME))


def test_names_persian_and_english_are_removed(redacted):
    for word in ("سپیده", "کوهستانی", "Sepideh", "Kohestani", "sepideh"):
        assert word not in redacted
    assert redacted.startswith("[NAME]\n")
    assert "[NAME] is a team player" in redacted


def test_contact_and_identifier_patterns_are_removed(redacted):
    for leaked in (
        "@example.com",
        "0912",
        "345 6789",
        "linkedin.com",
        "@sepidehk42",
        "0012345678",
        "81746",
        "1372/04/11",
    ):
        assert leaked not in redacted
    for placeholder in ("[EMAIL]", "[PHONE]", "[URL]", "[NATIONAL_ID]", "[POSTAL_CODE]", "[BIRTH_DATE]", "[ADDRESS]"):
        assert placeholder in redacted


def test_work_history_signal_is_preserved(redacted):
    for kept in ("فناوران ابری سپهر", "Kavir Systems", "1398/01/01 - 1402/06/30", "2016-2019", "Python", "FastAPI"):
        assert kept in redacted


@pytest.mark.parametrize(
    "phone",
    [
        "0912 345 6789",
        "09123456789",
        "+98 912 345 6789",
        "+98 (0) 912-345-6789",
        "0098-9123456789",
        "9123456789",
        "021-88776655",
        "(021) 8877 6655",
        "+98 21 8877 6655",
        "+44 20 7946 0958",
    ],
)
def test_every_phone_format_is_removed(phone):
    assert redact_patterns(f"تماس: {phone} لطفاً") == "تماس: [PHONE] لطفاً"


def test_persian_digit_phone_is_removed_after_normalization():
    assert redact_patterns(normalize_text("موبایل: ۰۹۱۲۳۴۵۶۷۸۹")) == "موبایل: [PHONE]"


@pytest.mark.parametrize(
    "text",
    ["https://example.org/cv", "www.example.org", "github.com/someone", "t.me/someone", "linkedin.com/in/x"],
)
def test_urls_and_profiles_are_removed(text):
    assert redact_patterns(f"پروفایل: {text}") == "پروفایل: [URL]"


def test_known_phone_is_removed_even_in_unusual_formatting():
    redactor = Redactor.for_identity(Identity(phones=("0912-345-6789",)))
    assert redactor.resume_text("شماره 0 9 1 2 3 4 5 6 7 8 9 است") == "شماره [PHONE] است"


def test_job_location_is_kept_but_resume_location_removed():
    redactor = Redactor.for_identity(Identity(locations=("اصفهان",)))
    assert redactor.resume_text("ساکن اصفهان") == "ساکن [LOCATION]"
    assert redactor.other_text("محل کار: اصفهان") == "محل کار: اصفهان"


def test_short_common_words_are_not_treated_as_names():
    redactor = Redactor.for_identity(Identity(names=("A", "Sara")))
    assert redactor.resume_text("A senior developer named Sara") == "A senior developer named [NAME]"


def test_identity_hashes_never_contain_plaintext():
    hashes = identity_hashes(SAMPLE_IDENTITY)
    joined = " ".join(hashes)
    assert hashes and all(len(value) == len(hashes[0]) for value in hashes)
    for word in ("سپیده", "sepideh", "9123456789"):
        assert word not in joined


# ---------------------------------------------------------------------------
# دورزدن‌هایی که بازبینی امنیتی پیدا کرد
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    ["سال تولد: 1370", "متولد سال 1370", "تولد: 1370/05/12", "Born in 1990", "DOB: 12/05/1990", "متولد 12 مرداد 1370"],
)
def test_birth_date_variants_are_removed(text):
    assert "[BIRTH_DATE]" in redact_patterns(text)
    assert not any(char.isdigit() for char in redact_patterns(text))


@pytest.mark.parametrize(
    "text",
    [
        "behance.net/saraahmadi",
        "fb.com/saraahmadi",
        "sara.github.io",
        "sara-ahmadi.ir",
        "medium.com/@sara",
        "x.com/sara",
    ],
)
def test_any_domain_or_profile_url_is_removed(text):
    assert redact_patterns(f"وب: {text} و") == "وب: [URL] و"


def test_technology_names_shaped_like_domains_are_kept():
    text = "ASP.NET Core، Socket.io، Node.js و Vue.js"
    assert redact_patterns(text) == text


@pytest.mark.parametrize(
    "phone",
    [
        "0912 345 67 89",
        "0912/345/6789",
        f"0912{ZWNJ}345{ZWNJ}6789",
        "021 88 77 66 55",
        "00 44 20 7946 0958",
        "(+98) 912 345 6789",
    ],
)
def test_more_phone_formats_are_removed(phone):
    assert "[PHONE]" in redact_patterns(f"شماره {phone} است")
    assert not any(char.isdigit() for char in redact_patterns(f"شماره {phone} است"))


def test_labeled_short_landline_is_removed():
    assert redact_patterns("تلفن: 88776655") == "تلفن: [PHONE]"


@pytest.mark.parametrize(
    "text", ["(1398/01/01 - 1402/06/30)", "2015-2018 و 2019-2021", "حقوق 15000000 تومان", "1395 - 1398"]
)
def test_dates_and_amounts_are_not_mistaken_for_phones(text):
    assert redact_patterns(text) == text


@pytest.mark.parametrize("text", ["ID-0012345678", "کد ملی 001 234 5678", "کد ملی: 001-234567-8"])
def test_national_id_variants_are_removed(text):
    assert "[NATIONAL_ID]" in redact_patterns(text)


def test_spaced_postal_code_is_removed():
    assert redact_patterns("کد پستی: 12345 67890") == "کد پستی: [POSTAL_CODE]"


def test_labeled_address_line_is_removed():
    assert redact_patterns("آدرس: تهران، خیابان ساختگی، پلاک 12\nسوابق") == "آدرس: [ADDRESS]\nسوابق"


def test_profile_name_is_normalized_like_resume_text():
    redactor = Redactor.for_identity(Identity(names=("علي كريمي", "محمد رضا")))
    text = normalize_text("علی کریمی و محمدرضا")
    assert redactor.resume_text(text) == "[NAME] و [NAME]"


def test_resume_header_line_is_treated_as_a_name():
    from app.datasets.finetune.anonymize import header_name, with_header_name

    resume = "Sara Ahmadi\nBackend Developer\nسابقه"
    identity = with_header_name(Identity(names=("سارا احمدی",)), resume)
    assert Redactor.for_identity(identity).resume_text(resume).startswith("[NAME]\n")
    assert header_name("Senior Backend Developer\nسابقه") is None
    assert header_name("رزومه\nعلی") is None


def test_stored_phone_with_persian_digits_is_removed_from_latin_text():
    redactor = Redactor.for_identity(Identity(phones=("۰۹۱۲۳۴۵۶۷۸۹",)))
    assert redactor.resume_text("شماره 912 345 6789") == "شماره [PHONE]"
    assert identity_hashes(Identity(phones=("۰۹۱۲۳۴۵۶۷۸۹",))) == identity_hashes(Identity(phones=("09123456789",)))
