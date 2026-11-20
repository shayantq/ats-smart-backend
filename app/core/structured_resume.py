"""پارس مستند؛ دادهٔ مجهول با حدس مدل یا اطلاعات حساب پر نمی‌شود."""

import hashlib
import re
import unicodedata
from collections import Counter
from datetime import date
from urllib.parse import urlparse

from app.core.resume_dates import (
    RANGE,
    CURRENT,
    ENDPOINT,
    MONTHS_FA,
    MONTH_PATTERN,
    date_range,
    endpoint,
    normalize,
    totals,
)
from app.core.resume_sections import heading
from app.schemas.structured_resume import StructuredResume

PARSER_VERSION = 10
TEACHING_TITLE = re.compile(r"^(?:تدریس|مدرس|lecturer|instructor|teaching)\s+\S", re.I)
TEACHING_ORG = re.compile(
    r"آموزشگاه|دانشگاه|دانشکده|موسسه|مؤسسه|هنرستان|تیم آموزشی|\buniversity\b|\bacademy\b|\binstitute\b", re.I
)
PERSIAN_MONTH_SUFFIX = re.compile(rf"\b({'|'.join(MONTHS_FA)})\s*ماه(?=\s*(?:\d|تا|$))")
TEACHING_DATE_LABEL = re.compile(r"^(?:(?:تاریخ|زمان|date)\s*[:：]\s*|سال\s+)", re.I)

ROLE = re.compile(
    r"\b(?:engineer|developer|intern|manager|analyst|consultant|designer|accountant|nurse|teacher|technician|specialist"
    r"|lead|architect)\b"
    r"|کار\s*آموز|توسعه|مهندس|کارشناس|مدیر|برنامه.?نویس|طراح|حسابدار|پزشک|پرستار|معلم",
    re.I,
)
ACTION = re.compile(
    r"^(?:[•●▪*]|[e¢]\s|developed\b|collaborated\b|assisted\b|created\b|utilized\b|demonstrated\b|participated\b"
    r"|conducted\b|provided\b|achieved\b|built\b|implemented\b|designed\b|maintained\b"
    r"|(?:توسعه|پیاده سازی|طراحی|نگهداری|بهینه سازی|ساخت|راه اندازی|مدیریت|تحلیل)\s+"
    r"(?!دهنده\b|گر\b)(?:.*\s)?(?:با|برای)\s)",
    re.I,
)
ORG = re.compile(
    r"\b(?:corp|inc|llc|ltd|systems|innovations|labs?|company|group|services|university|academy|institute)\b"
    r"|شرکت|سازمان|دانشگاه|مؤسسه",
    re.I,
)
EMAIL = re.compile(r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE = re.compile(r"(?:\+|00)?\d[\d ()-]{6,}\d")
URL = re.compile(r"(?:https?://|www\.)[^\s<>]+|(?:linkedin\.com|github\.com)/[^\s<>]+", re.I)


def evidence(text, layout=None):
    if not text or not text.strip():
        return []
    matches = []
    needle = normalize(text)
    for page in (layout or {}).get("pages", []):
        for block in page.get("blocks", []):
            value = normalize(block["text"])
            if not block.get("excluded_reason") and value and (value in needle or needle in value):
                matches.append(dict(text=block["text"], page=page["number"], bbox=block["bbox"], block_id=block["id"]))
    return matches or ([dict(text=text)] if text.strip() else [])


def fact(value, source="", layout=None, status="extracted", reason=None):
    refs = evidence(source, layout)
    precise = [ref for ref in refs if value and normalize(value) in normalize(ref["text"])]
    return dict(value=value, status=status if value is not None else "missing", evidence=precise or refs, reason=reason)


def section_rows(text, layout=None):
    lines = text.splitlines()
    native_rows = [
        (line.strip(), block)
        for page in (layout or {}).get("pages", [])
        for block in page.get("blocks", [])
        if not block.get("excluded_reason")
        for line in block["text"].splitlines()
        if line.strip()
    ]
    # در صورت ناهماهنگی متن و صفحه، شواهد بصری به خط دیگری منتسب نمی‌شوند.
    aligned = [line for line, _ in native_rows] == [line.strip() for line in lines if line.strip()]
    blocks = iter(block for _, block in native_rows) if aligned else iter(())
    result = {"header": []}
    current = "header"
    for raw in lines:
        block = next(blocks, {}) if raw.strip() else {}
        label = heading(raw)
        if label:
            current = label
            result.setdefault(current, [])
        else:
            result[current].append((raw.strip(), block))
    return result


def sections(text):
    return {section: [line for line, _ in rows] for section, rows in section_rows(text).items()}


def title_size(rows):
    styles = [block["native_style"] for _, block in rows if block.get("native_style")]
    body = Counter(style["size"] for style in styles if not style["bold"])
    if not body:
        return None
    regular_size = body.most_common(1)[0][0]
    headings = Counter(style["size"] for style in styles if style["bold"] and style["size"] > regular_size)
    return headings.most_common(1)[0][0] if headings else None


def title_line(text):
    stripped = RANGE.sub("", normalize(text)).strip(" |@,-")
    return bool(ROLE.search(stripped) and len(stripped.split()) <= 13 and not ACTION.search(stripped))


def find_date(text):
    value = normalize(text)
    value = re.sub(
        rf"({MONTH_PATTERN})\s+تا\s*({CURRENT})\s*(\d{{4}})", lambda m: f"{m[1]} {m[3]} تا {m[2]}", value, flags=re.I
    )
    match = RANGE.search(value)
    if not match:
        reverse = re.fullmatch(rf"تا\s*({CURRENT})\s*(\d{{4}})\s+({MONTH_PATTERN})", value, re.I)
        if reverse:
            match = RANGE.search(f"{reverse[3]} {reverse[2]} تا {reverse[1]}")
        else:
            reverse = re.fullmatch(
                rf"({CURRENT})\s+تا\s+(?:(\d{{4}})\s+({MONTH_PATTERN})|({MONTH_PATTERN})\s*(\d{{4}}))", value, re.I
            )
            if reverse and any(ch in value for ch in "تیرمهرآبانخردادفروردین"):
                month, year = (reverse[3], reverse[2]) if reverse[2] else (reverse[4], reverse[5])
                match = RANGE.search(f"{month} {year} تا {reverse[1]}")
        if match is None:
            calendar = calendar_line(text)
            reverse = re.fullmatch(rf"({CURRENT})\s*(?:[-–—]|تا)\s*({ENDPOINT})", calendar, re.I)
            if reverse:
                calendar = f"{reverse[2]} تا {reverse[1]}"
            else:
                ongoing = re.fullmatch(rf"({ENDPOINT})\s*(?:[-–—]|تا)?\s*({CURRENT})", calendar, re.I)
                if ongoing:
                    calendar = f"{ongoing[1]} تا {ongoing[2]}"
            match = RANGE.fullmatch(calendar)
            if match is None:
                # استخراج RTL گاهی سال‌های هر دو سر بازه را به انتهای همان سطر منتقل می‌کند.
                split_years = re.fullmatch(
                    rf"({MONTH_PATTERN})\s*تا\s*({MONTH_PATTERN})\s+(\d{{4}})\s+(\d{{4}})", calendar, re.I
                )
                same_year = re.fullmatch(rf"({MONTH_PATTERN})\s+(\d{{4}})\s*تا\s*({MONTH_PATTERN})", calendar, re.I)
                trailing_year = re.fullmatch(rf"({MONTH_PATTERN})\s*تا\s*({MONTH_PATTERN})\s+(\d{{4}})", calendar, re.I)
                if split_years:
                    match = RANGE.fullmatch(f"{split_years[1]} {split_years[3]} تا {split_years[2]} {split_years[4]}")
                elif same_year:
                    match = RANGE.fullmatch(f"{same_year[1]} {same_year[2]} تا {same_year[3]} {same_year[2]}")
                elif trailing_year:
                    match = RANGE.fullmatch(
                        f"{trailing_year[1]} {trailing_year[3]} تا {trailing_year[2]} {trailing_year[3]}"
                    )
    return match


def calendar_line(line):
    value = normalize(
        "".join(
            " " if unicodedata.category(c) in {"Co", "Cf"} else "-" if unicodedata.category(c) == "Pd" else c
            for c in line
        )
    ).replace("لغایت", "تا")
    value = TEACHING_DATE_LABEL.sub("", value.strip("•●▪*–—|- :"))
    value = PERSIAN_MONTH_SUFFIX.sub(r"\1 ", value)
    value = re.sub(rf"\b({MONTH_PATTERN})\s*(?=\d{{4}}\b)", r"\1 ", value, flags=re.I)
    return value


def record_date(line, reference):
    value = calendar_line(line)
    season = re.fullmatch(r"(?:بهار|تابستان|پاییز|زمستان)\s+(\d{4})|(\d{4})\s+(?:بهار|تابستان|پاییز|زمستان)", value)
    if season:
        value = season[1] or season[2]
    if not re.fullmatch(ENDPOINT, value, re.I):
        return None
    try:
        earliest, _, _, year = endpoint(value, reference)
    except (ValueError, TypeError, OverflowError):
        return None
    display = "".join(c for c in line if c in "\u200c\u200d" or unicodedata.category(c) not in {"Co", "Cf"}).strip()
    return display if year and earliest <= reference else None


def location_line(text):
    return bool(re.fullmatch(r"[A-Za-z .'-]+,\s*(?:[A-Z]{2}|[A-Za-z ]+)(?:,\s*[A-Za-z ]+)?", text.strip()))


def activities(text, layout=None, reference=None):
    reference = reference or date.today()
    result = []
    for section, rows in section_rows(text, layout).items():
        if section not in {"experience", "internships", "freelance", "volunteering", "projects", "teaching"}:
            continue
        pending = None
        pre_company = None
        project_break = False
        visual_size = title_size(rows)
        previous_title = None

        def flush():
            nonlocal pending
            if not pending:
                return
            src = "\n".join(pending.pop("lines"))
            values = pending.pop("values")
            duration = values.get("duration")
            dates = date_range(duration, reference)
            fields = {
                key: fact(values.get(key), src, layout)
                for key in ("job_title", "company", "duration", "location", "client", "engagement_type")
            }
            if pending["kind"] == "project":
                fields["project_name"] = fields.pop("job_title")
            if pending["kind"] == "teaching" and values.get("audience"):
                fields["audience"] = fact(values["audience"], src, layout)
            if values.get("date") and not duration:
                fields["date"] = fact(values["date"], values["date"], layout)
            if duration and dates["status"] != "valid":
                fields["duration"].update(
                    status="invalid" if dates["status"] == "invalid" else "ambiguous", reason=dates["error_code"]
                )
            key = (
                pending["kind"],
                normalize(values.get("job_title") or ""),
                normalize(values.get("company") or ""),
                str(dates["start"]),
                str(dates["end"]),
            )
            if dates["status"] != "valid":
                key += (normalize(src),)
            existing = next((x for x in result if x.get("_key") == key), None)
            if existing:
                for claim in pending["claims"]:
                    if claim not in existing["claims"]:
                        existing["claims"].append(claim)
            else:
                result.append(
                    dict(
                        id=f"activity-{len(result)+1}",
                        kind=pending["kind"],
                        fields=fields,
                        dates=dates,
                        claims=pending["claims"],
                        source="resume_evidence_v3",
                        _key=key,
                    )
                )
            pending = None

        for line, block in rows:
            if not line:
                project_break = True
                continue
            match = find_date(line)
            is_title = title_line(line) and not re.match(r"^(?:شرکت|سازمان)\s+", line)
            if section == "teaching":
                candidate = normalize(line)
                while candidate and (candidate[0] in "•●▪*- " or unicodedata.category(candidate[0]) in {"Co", "Cf"}):
                    candidate = candidate[1:]
                is_title = bool(TEACHING_TITLE.search(candidate) and len(candidate.split()) <= 16)
            is_project = (
                section == "projects"
                and (pending is None or "|" in line or project_break)
                and len(line) < 110
                and not ACTION.search(line)
                and ":" not in line
            )
            if section == "projects":
                is_title = False
            if visual_size is not None and block.get("native_style"):
                style = block["native_style"]
                title = style["bold"] and style["size"] == visual_size
                is_title, is_project = title and section != "projects", title and section == "projects"
            project_break = False
            if is_title or is_project:
                if (
                    visual_size is not None
                    and pending
                    and previous_title
                    and len(pending["lines"]) == 1
                    and previous_title.get("page") == block.get("page")
                    and previous_title.get("column") == block.get("column")
                    and previous_title.get("bbox")
                    and block.get("bbox")
                    and -2 <= block["bbox"][1] - previous_title["bbox"][3] <= 12
                    and line.count(")") > line.count("(")
                ):
                    pending["values"]["job_title"] += " " + line
                    pending["lines"].append(line)
                    continue
                if (
                    pending
                    and not pending["values"].get("company")
                    and not pending["values"].get("duration")
                    and re.search(r"(?:software|senior|junior)$", pending["values"]["job_title"], re.I)
                ):
                    pending["values"]["job_title"] += " " + RANGE.sub("", line).strip()
                    pending["lines"].append(line)
                    continue
                flush()
                title = normalize(line) if match else line
                if match:
                    title = (normalize(line)[: match.start()] + normalize(line)[match.end() :]).strip(" |,-")
                pieces = re.split(r"\s*[|｜]\s*|\s+@\s+", title, maxsplit=1)
                idx = 0 if is_project else next((i for i, s in enumerate(pieces) if ROLE.search(normalize(s))), 0)
                role = pieces[idx].strip()
                if section == "teaching":
                    role = candidate if not match and len(pieces) == 1 else role
                company = pieces[1 - idx].strip() if len(pieces) == 2 else pre_company
                # در برخی PDFهای RTL، نشان کارآموزی پس از جداکننده و پیش از نام لاتین شرکت می‌افتد.
                if len(pieces) == 2 and idx == 0 and section != "projects":
                    misplaced = re.fullmatch(
                        r"(کار\s*آموز)\s+([A-Za-z][A-Za-z0-9 .&'-]+)",
                        unicodedata.normalize("NFKC", pieces[1]),
                    )
                    if misplaced and ROLE.search(normalize(pieces[0])):
                        role = misplaced[1] + " " + role
                        company = misplaced[2]
                if normalize(role).endswith("کارآموز") and "توسعه" in normalize(role):
                    role = " ".join(reversed(role.split()))
                kind = (
                    "project"
                    if section == "projects"
                    else (
                        "volunteering"
                        if section == "volunteering"
                        else (
                            "freelance"
                            if section == "freelance"
                            else (
                                "internship"
                                if re.search(r"\bintern\b|کار\s*آموز", normalize(role), re.I)
                                or section == "internships"
                                else "employment"
                            )
                        )
                    )
                )
                if section == "teaching":
                    kind = "teaching"
                pending = dict(
                    kind=kind,
                    values=dict(
                        job_title=role,
                        company=company if kind != "project" else None,
                        duration=match.group() if match else None,
                    ),
                    lines=([pre_company] if pre_company and len(pieces) == 1 and kind != "project" else []) + [line],
                    claims=[],
                )
                previous_title = block
                pre_company = None
            elif pending:
                pending["lines"].append(line)
                values = pending["values"]
                organization = list(ORG.finditer(line))
                split_at = organization[-1].end() if organization else 0
                inline_location = line[split_at:].strip() if split_at else ""
                audience = re.match(r"^(?:مخاطبان?|audience|participants)\s*[:：]\s*(.+)$", line, re.I)
                teaching_near_title = pending["kind"] == "teaching" and len(pending["lines"]) <= 4
                allow_event_date = teaching_near_title or (pending["kind"] == "project" and len(pending["lines"]) <= 4)
                event_date = record_date(line, reference) if allow_event_date and not match else None
                if pending["kind"] == "teaching" and audience:
                    values["audience"] = audience[1]
                elif match and not values.get("duration") and (pending["kind"] != "teaching" or teaching_near_title):
                    values["duration"] = match.group()
                elif event_date:
                    values.setdefault("date", event_date)
                elif not values.get("company") and split_at and location_line(inline_location):
                    values["company"] = line[:split_at].strip()
                    values["location"] = inline_location
                elif location_line(line):
                    values["location"] = line
                elif re.match(r"^(?:client|مشتری|کارفرما(?:\s*/\s*درخواست کننده)?)\s*:", normalize(line), re.I):
                    values["client"] = line.split(":", 1)[1].strip()
                elif re.match(r"^(?:type|نوع همکاری)\s*:", line, re.I):
                    values["engagement_type"] = line.split(":", 1)[1].strip()
                elif (
                    pending["kind"] != "project"
                    and (pending["kind"] != "teaching" or TEACHING_ORG.search(line))
                    and not values.get("company")
                    and len(line.split()) <= 7
                    and len(line) < 85
                    and not ACTION.search(line)
                    and not match
                    and not re.search(r"[:.!؟]", line)
                ):
                    values["company"] = line
                else:
                    pending["claims"].append(
                        fact(line, line, layout, status="attributed", reason="resume_claim_not_independently_verified")
                    )
            elif ORG.search(line) and len(line) < 90:
                pre_company = line
        flush()
    for record in result:
        record.pop("_key", None)
    return result


def legacy_work(text, layout=None, reference=None):
    output = []
    for record in activities(text, layout, reference):
        if record["kind"] not in {"employment", "internship", "freelance"}:
            continue
        f = record["fields"]
        output.append(
            dict(
                company=f["company"]["value"],
                job_title=f["job_title"]["value"],
                duration=f["duration"]["value"],
                evidence="\n".join(dict.fromkeys(e["text"] for e in f["job_title"]["evidence"])),
                source="resume_evidence_v3",
            )
        )
    return output


def identity(text, layout):
    header = sections(text).get("header", [])
    names = []
    for line in header:
        value = line.strip()
        if (
            2 <= len(value.split()) <= 5
            and len(value) < 70
            and not ROLE.search(value)
            and not ORG.search(value)
            and not any(c in value for c in "@|:/,+0123456789")
            and all(c.isalpha() or c in " -'’\u200c" for c in value)
        ):
            names.append(value)
    names = list(dict.fromkeys(names))
    name = fact(names[0], names[0], layout) if len(names) == 1 else fact(None, "\n".join(names), layout)
    if len(names) > 1:
        name.update(status="ambiguous", reason="multiple_name_candidates")
    contacts = []
    for found in EMAIL.finditer(text):
        address = found.group()
        if any(c["value"] == address for c in contacts):
            continue
        generic = address.split("@")[0].lower() in {
            "help",
            "support",
            "info",
            "contact",
            "hello",
            "noreply",
            "no-reply",
        }
        contacts.append(
            fact(
                address,
                address,
                layout,
                status="ambiguous" if generic else "extracted",
                reason="generic_contact_requires_review" if generic else "syntax_only_not_ownership_verified",
            )
        )
    for found in PHONE.finditer(text):
        phone = found.group().strip()
        digits = re.sub(r"\D", "", normalize(phone))
        if 10 <= len(digits) <= 15 and (phone.startswith(("+", "00")) or digits.startswith("09")):
            if not any(c["value"] == phone for c in contacts):
                contacts.append(fact(phone, phone, layout, reason="syntax_only_not_ownership_verified"))
    links = []
    for found in URL.finditer(text):
        value = found.group().rstrip(".,;)")
        url = urlparse(value if value.lower().startswith(("https://", "http://")) else "https://" + value)
        if url.scheme in {"http", "https"} and url.hostname and not url.username:
            if not any(x["value"] == value for x in links):
                links.append(fact(value, value, layout, reason="link_not_fetched_or_verified"))
    locations = []
    for line in header + sections(text).get("contact", []):
        for part in re.split(r"[|｜•]", line):
            part = "".join(c for c in unicodedata.normalize("NFKC", part) if unicodedata.category(c) != "Cf").strip(
                " ,،; "
            )
            if location_line(part) and part not in locations:
                locations.append(part)
    return (
        dict(name=name, location=fact(locations[0], locations[0], layout) if len(locations) == 1 else fact(None)),
        contacts,
        links,
    )


def qualifications(text, kind, layout, reference=None):
    reference = reference or date.today()
    result = []
    rows = [(line, block) for line, block in section_rows(text, layout).get(kind, []) if line]
    if kind == "languages":
        language_names = (
            r"english|persian|farsi|german|french|arabic|spanish|turkish|russian|chinese|japanese|italian"
            r"|فارسی|انگلیسی|آلمانی|فرانسوی|عربی|ترکی|روسی|اسپانیایی|چینی|ژاپنی|ایتالیایی"
        )
        pattern = re.compile(
            rf"^({language_names})\s*[-–—:]?\s*(upper[- ]intermediate|native|advanced|fluent"
            r"|intermediate|basic|beginner|[abc][12]"
            r"|متوسط رو به بالا|مادری|پیشرفته|متوسط|مبتدی)(?:\s|$)",
            re.I,
        )
        pending_language = None
        for line in [part.strip() for raw, _ in rows for part in re.split(r"[|｜;؛]", raw) if part.strip()]:
            match = pattern.search(line)
            if not match and pending_language:
                match = pattern.search(pending_language + " " + line)
            if match:
                result.append(
                    dict(
                        fields={
                            "language": fact(
                                match[1], (pending_language + "\n" if pending_language else "") + line, layout
                            ),
                            "level": fact(
                                match[2], line, layout, status="attributed", reason="self_reported_proficiency"
                            ),
                        }
                    )
                )
                pending_language = None
            elif re.fullmatch(language_names, line, re.I):
                if pending_language:
                    result.append(
                        dict(fields={"language": fact(pending_language, pending_language, layout), "level": fact(None)})
                    )
                pending_language = line
        if pending_language:
            result.append(
                dict(fields={"language": fact(pending_language, pending_language, layout), "level": fact(None)})
            )
        return result
    current = None
    visual_size = title_size(rows)
    for line, block in rows:
        if current and normalize(line) in {"certification", "certificate", "گواهی نامه"}:
            previous = current["fields"]["title"]["value"]
            current["fields"]["title"] = fact(previous + " " + line, previous + "\n" + line, layout)
            continue
        expiry = re.match(r"^(?:expiry|expires|valid until|انقضا|اعتبار تا)\s*:?\s*(.+)$", line, re.I)
        if current and expiry:
            from app.core.resume_dates import endpoint

            current["fields"]["expiry"] = fact(expiry[1], line, layout)
            try:
                low, high, precision, year = endpoint(expiry[1], reference)
                current["expiry_status"] = (
                    "expired_claim" if high < reference else "not_expired_claim" if low > reference else "uncertain"
                )
            except (ValueError, TypeError):
                current["expiry_status"] = "unknown"
            continue
        starts = (
            bool(re.search(r"bachelor|master|ph\.?d|bsc|msc|کارشناسی|کاردانی|دکتری|دیپلم", line, re.I))
            if kind == "education"
            else bool(re.search(r"certif|course|دوره|گواهی", line, re.I))
        )
        if visual_size is not None and block.get("native_style"):
            style = block["native_style"]
            starts = style["bold"] and style["size"] == visual_size
            if current is None and not starts:
                continue
        if current is None or starts:
            current = dict(
                fields={"title": fact(line, line, layout), "institution": fact(None), "date": fact(None)},
                source="resume_text",
                verification="not_independently_verified",
            )
            result.append(current)
            match = RANGE.search(normalize(line))
            if match:
                current["fields"]["date"] = fact(match.group(), line, layout)
        elif ORG.search(line) or re.match(r"^موسسه\s*:", normalize(line)):
            current["fields"]["institution"] = fact(line, line, layout)
            year = re.search(r"\b(?:19|20|13|14)\d{2}\b", normalize(line))
            if year:
                current["fields"]["date"] = fact(year.group(), line, layout)
        elif find_date(line) or record_date(line, reference):
            current["fields"]["date"] = fact(record_date(line, reference) or line, line, layout)
        elif re.search(r"(?:credential|شناسه)\s*(?:id)?\s*:", line, re.I):
            current["fields"]["credential_id"] = fact(line.split(":", 1)[1].strip(), line, layout)
    return result


def build_structured(text, layout=None, reference=None):
    reference = reference or date.today()
    records = activities(text, layout, reference)
    who, contacts, links = identity(text, layout)
    overlaps = []
    valid = [r for r in records if r["dates"]["status"] == "valid" and r["kind"] != "project"]
    for i, a in enumerate(valid):
        for b in valid[:i]:
            start = max(a["dates"]["start"]["earliest"], b["dates"]["start"]["earliest"])
            end = min(a["dates"]["end"]["latest"], b["dates"]["end"]["latest"])
            if start < end:
                certain_start = max(a["dates"]["start"]["latest"], b["dates"]["start"]["latest"])
                certain_end = min(a["dates"]["end"]["earliest"], b["dates"]["end"]["earliest"])
                overlaps.append(
                    dict(
                        activities=[a["id"], b["id"]],
                        status="source_confirmed" if certain_start < certain_end else "possible",
                        earliest=start,
                        latest=end,
                    )
                )
    ordered = sorted(valid, key=lambda r: r["dates"]["start"]["earliest"])
    gaps = []
    frontier = None
    for r in ordered:
        if frontier and frontier < r["dates"]["start"]["earliest"]:
            gaps.append(
                dict(start=frontier, end=r["dates"]["start"]["earliest"], interpretation="resume_may_be_incomplete")
            )
        frontier = max(frontier or "", r["dates"]["end"]["latest"])
    raw_sections = sections(text)
    awards = []
    for line in filter(None, raw_sections.get("awards", [])):
        event_date = record_date(line, reference)
        if awards and event_date and "date" not in awards[-1]["fields"]:
            awards[-1]["fields"]["date"] = fact(event_date, line, layout)
        else:
            awards.append(dict(fields={"title": fact(line, line, layout, status="attributed")}))
    warnings = []
    if who["name"]["status"] == "ambiguous":
        warnings.append("multiple_identity_candidates")
    if any(r["dates"]["status"] != "valid" for r in records):
        warnings.append("some_activity_dates_unknown_or_invalid")
    if raw_sections.get("experience") and not any(
        r["kind"] in {"employment", "internship", "freelance"} for r in records
    ):
        warnings.append("employment_section_without_supported_records")
    document = dict(
        version="resume-structured-v1",
        source_sha256=hashlib.sha256(text.encode()).hexdigest(),
        reference_date=reference.isoformat(),
        identity=who,
        contacts=contacts,
        links=links,
        activities=records,
        education=qualifications(text, "education", layout, reference),
        certifications=qualifications(text, "certifications", layout, reference),
        languages=qualifications(text, "languages", layout, reference),
        publications=[
            dict(fields={"title": fact(x, x, layout, status="attributed")})
            for x in raw_sections.get("publications", [])
            if x
        ],
        awards=awards,
        totals=totals(records),
        overlaps=overlaps,
        gaps=gaps,
        warnings=warnings,
    )
    return StructuredResume.model_validate(document).model_dump()
