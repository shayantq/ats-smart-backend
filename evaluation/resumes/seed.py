"""تعریف اولیهٔ corpus؛ فقط برای ساخت نسخهٔ جدید و بازبینی صریح، نه بازنویسی holdout."""

from evaluation.resumes.contract import Case, Record


def cases():
    result = []
    variants = [
        ("en-inline", "en", "single", "text", "Junior Software Engineer", "01/2024 - 12/2024"),
        ("fa-month", "fa", "single", "text", "مهندس نرم افزار", "تیر ۱۴۰۳ تا آبان ۱۴۰۴"),
        ("en-columns", "en", "columns", "image", "Software Engineering Intern", "06/2023 - 12/2023"),
        ("mixed-hybrid", "mixed", "single", "hybrid", "توسعه دهنده Python", "1400/01 تا 1402/01"),
        ("fa-arabic", "fa", "single", "image", "کارشناس نرم افزار", "١٤٠٠ - ١٤٠٢"),
        ("en-table", "en", "table", "text", "Software Engineer", "2020 - 2022"),
        ("en-unknown", "en", "single", "text", "Developer", None),
        ("fa-duplicate", "fa", "single", "text", "کارآموز توسعه", "1401 - 1403"),
        ("en-overlap", "en", "single", "text", "Engineer", "2020/01 - 2022/01"),
        ("en-volunteer", "en", "columns", "text", "Volunteer Developer", "01/2022 - 04/2022"),
        ("fa-ongoing", "fa", "single", "text", "مدیر فنی", "تیر ۱۴۰۵ تا اکنون"),
        ("en-project", "en", "single", "text", "Developer", "2021 - 2023"),
    ]
    for i, (key, lang, layout, kind, title, duration) in enumerate(variants):
        employer = f"Synthetic Lab {i+1}"
        header = "سوابق کاری" if lang != "en" else "EXPERIENCE"
        label = "volunteering" if key == "en-volunteer" else "project" if key == "en-project" else "employment"
        if label != "employment":
            header = "VOLUNTEERING" if label == "volunteering" else "PROJECTS"
        start = ["Synthetic Person " + str(i + 1), f"fixture{i+1}@example.invalid", header]
        block = [title + " | " + employer, duration or "Date not supplied"]
        if key == "en-inline":
            block = [title + " " + duration, employer]
        expected = [
            Record(kind=label, fields=dict(company=employer, job_title=title, duration=duration), evidence=block)
        ]
        if key == "fa-duplicate":
            block *= 2
        if key == "en-overlap":
            extra = ["Senior Engineer | " + employer, "2021/01 - 2023/01"]
            expected.append(
                Record(
                    kind="employment",
                    fields=dict(company=employer, job_title="Senior Engineer", duration=extra[1]),
                    evidence=extra,
                )
            )
            block += extra
        end = ["SKILLS", "Python", "Git", "EDUCATION", "BSc Computer Science", "Synthetic Academy"]
        expected += [
            Record(kind="identity", fields={"name": start[0], "email": start[1], "phone": None}, evidence=start[:2]),
            Record(
                kind="education",
                fields={"degree": "BSc Computer Science", "university": "Synthetic Academy"},
                evidence=end[-2:],
            ),
        ]
        expected += [Record(kind="skill", fields={"name": x}, evidence=[x]) for x in ("Python", "Git")]
        pages = [start + block + end]
        if kind == "hybrid":
            pages = [start + block, end]
        result.append(
            Case(
                id=key,
                lineage=key,
                language=lang,
                layout=layout,
                input_type=kind,
                pages=pages,
                expected=expected,
                sections=[header, "SKILLS", "EDUCATION"],
                precision={
                    "duration": (
                        "unknown" if duration is None else "month" if "/" in duration or "تیر" in duration else "year"
                    )
                },
            )
        )
    # همان محتوا و پاسخ در قالب دیگر، در همان lineage و split باقی می‌ماند.
    result.append(result[0].model_copy(update={"id": "en-inline-image", "input_type": "image"}))
    result.append(
        Case(
            id="corrupt",
            lineage="corrupt",
            language="en",
            layout="single",
            input_type="corrupt",
            pages=[],
            expected=[],
            sections=[],
            expected_error="unreadable_resume",
        )
    )
    return result
