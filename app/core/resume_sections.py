"""واژگان مشترک مرز بخش‌ها؛ تشخیص مبهم هرگز به استخدام قطعی تبدیل نمی‌شود."""

import re
import unicodedata


def normalize(text):
    return " ".join(
        unicodedata.normalize("NFKC", text)
        .replace("\u200c", " ")
        .translate(str.maketrans("يك", "یک"))
        .casefold()
        .split()
    ).strip(" :：•")


ALIASES = {
    "teaching": (
        "teaching experience",
        "teaching history",
        "سوابق تدریس",
        "سابقه تدریس",
        "سوابق آموزشی و تدریس",
        "فعالیت های تدریس",
    ),
    "experience": (
        "experience",
        "work experience",
        "professional experience",
        "employment history",
        "career history",
        "تجربه کاری",
        "تجربیات شغلی",
        "سوابق کاری",
        "سوابق شغلی",
        "سابقه کار",
    ),
    "education": (
        "education",
        "academic background",
        "academic qualifications",
        "تحصیلات",
        "سوابق تحصیلی",
        "تحصیلات دانشگاهی",
    ),
    "projects": ("projects", "selected projects", "personal projects", "پروژه ها", "پروژه", "پروژه های شخصی"),
    "volunteering": (
        "volunteering",
        "volunteer experience",
        "community involvement",
        "فعالیت داوطلبانه",
        "فعالیت های داوطلبانه",
    ),
    "internships": ("internships", "internship experience", "سوابق کارآموزی", "کارآموزی"),
    "freelance": ("freelance", "freelance experience", "contract work", "فریلنسری", "پروژه های پیمانکاری"),
    "skills": ("skills", "technical skills", "core skills", "مهارت ها", "مهارت", "مهارت های فنی"),
    "languages": ("languages", "language skills", "زبان ها", "زبان"),
    "certifications": (
        "certifications",
        "certificates",
        "training / courses",
        "training",
        "courses",
        "گواهی نامه ها",
        "دوره ها",
        "دوره ها و گواهینامه ها",
        "دوره ها و گواهی نامه ها",
    ),
    "summary": ("summary", "profile", "about me", "professional summary", "درباره من", "خلاصه", "معرفی"),
    "interests": ("interests", "hobbies", "علاقه مندی ها", "علاقمندیها", "علاقهمندیها"),
    "strengths": ("strengths", "نقاط قوت"),
    "awards": ("awards", "honors", "جوایز", "افتخارات"),
    "publications": ("publications", "انتشارات", "مقالات"),
    "memberships": ("memberships", "عضویت ها"),
    "presentations": ("presentations", "talks", "ارائه ها و سخنرانی ها"),
    "contact": (
        "contact",
        "contact information",
        "personal information",
        "selected links",
        "links",
        "اطلاعات فردی",
        "اطلاعات تماس",
    ),
}
LOOKUP = {normalize(alias): kind for kind, aliases in ALIASES.items() for alias in aliases}


def heading(text):
    value = normalize(text)
    if value in LOOKUP:
        return LOOKUP[value]
    # نویسه‌های فونت و جهت متن فقط برای تطبیق عنوان کنار گذاشته می‌شوند.
    decorated = " ".join("".join(" " if unicodedata.category(c) in {"Co", "Cf"} else c for c in value).split())
    return LOOKUP.get(decorated.strip("•●▪◆◇·*-–—|:： "))


def annotate(blocks):
    current, column = "header", None
    for block in blocks:
        if block.get("excluded_reason"):
            continue
        if column is not None and column != block.get("column"):
            current = "unknown"
        column = block.get("column")
        label = heading(block["text"])
        if label:
            current = label
        block["section"] = current
        block["is_heading"] = bool(label)
        if current == "unknown":
            # تنها یک پیشنهاد برای بازبینی؛ هیچ فیلد واقع‌محور از آن ساخته نمی‌شود.
            block["section_status"] = "ambiguous"
            if re.search(r"\d{4}", block["text"]):
                block["suggested_section"] = "experience"
        else:
            block["section_status"] = "explicit" if label else "inherited"
