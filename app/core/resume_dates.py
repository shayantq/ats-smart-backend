"""تاریخ با دقت منبع و بازهٔ عدم قطعیت؛ بدون نسبت‌دادن روز ساختگی."""

import re
import unicodedata
from datetime import date, timedelta

import jdatetime

MONTHS_FA = "فروردین اردیبهشت خرداد تیر مرداد شهریور مهر آبان آذر دی بهمن اسفند".split()
MONTHS_EN = "january february march april may june july august september october november december".split()
MONTH_MAP = {name: i + 1 for i, name in enumerate(MONTHS_EN)}
MONTH_MAP.update({name[:3]: i + 1 for i, name in enumerate(MONTHS_EN)})
MONTH_MAP.update({name: i + 1 for i, name in enumerate(MONTHS_FA)})
MONTH_MAP["sept"] = 9
MONTH_PATTERN = "|".join(sorted(MONTH_MAP, key=len, reverse=True))
CURRENT = r"(?:تاکنون|اکنون|حال حاضر|present|current|now)"
ENDPOINT = (
    rf"(?:\d{{1,2}}\s+)?(?:{MONTH_PATTERN})\.?\s*\d{{4}}|\d{{4}}\s+(?:{MONTH_PATTERN})|"
    rf"\d{{4}}(?:[/.-]\d{{1,2}}(?:[/.-]\d{{1,2}})?)?|\d{{1,2}}/\d{{1,2}}/\d{{4}}|\d{{1,2}}/\d{{4}}|{CURRENT}"
)
RANGE = re.compile(rf"(?P<start>{ENDPOINT})\s*(?:[-–—]|تا|to)\s*(?P<end>{ENDPOINT})(?!\d)", re.I)


def normalize(value):
    return " ".join(
        unicodedata.normalize("NFKC", value)
        .translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩يك", "01234567890123456789یک"))
        .replace("\u200c", " ")
        .split()
    ).lower()


def endpoint(value, reference):
    value = normalize(value)
    if re.fullmatch(CURRENT, value, re.I):
        return reference, reference, "day", None
    value = value.replace(",", "")
    named = re.fullmatch(rf"(?:(\d{{1,2}})\s+)?({MONTH_PATTERN})\.?\s+(\d{{4}})", value, re.I)
    reverse_named = re.fullmatch(rf"(\d{{4}})\s+({MONTH_PATTERN})", value, re.I)
    if named:
        day = int(named[1]) if named[1] else None
        month, year = MONTH_MAP[named[2]], int(named[3])
    elif reverse_named:
        year, month, day = int(reverse_named[1]), MONTH_MAP[reverse_named[2]], None
    else:
        pieces = re.split(r"[/.-]", value)
        if not all(x.isdigit() for x in pieces) or len(pieces) > 3:
            raise ValueError("date_unknown")
        numbers = [int(x) for x in pieces]
        day = None
        if len(pieces[0]) == 4:
            year = numbers[0]
            month = numbers[1] if len(numbers) > 1 else None
            day = numbers[2] if len(numbers) > 2 else None
        elif len(numbers) == 2 and len(pieces[1]) == 4:
            month, year = numbers
        elif len(numbers) == 3 and len(pieces[2]) == 4:
            year = numbers[2]
            if numbers[0] > 12 and numbers[1] <= 12:
                day, month = numbers[:2]
            elif numbers[1] > 12 and numbers[0] <= 12:
                month, day = numbers[:2]
            else:
                raise ValueError("ambiguous_date")
        else:
            raise ValueError("ambiguous_date")
    cls = jdatetime.date if 1300 <= year < 1500 else date if 1900 <= year <= 2100 else None
    if cls is None:
        raise ValueError("calendar_unknown")
    low = cls(year, month or 1, day or 1)
    if day:
        high = low
    elif month:
        high = cls(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    else:
        high = cls(year + 1, 1, 1) - timedelta(days=1)

    def gregorian(x):
        return x.togregorian() if isinstance(x, jdatetime.date) else x

    return gregorian(low), gregorian(high), "day" if day else "month" if month else "year", year


def date_range(value, reference=None):
    reference = reference or date.today()
    result = dict(status="unknown", source=value, start=None, end=None, ongoing=False, error_code=None)
    if not value:
        return result
    text = normalize(value)
    reversed_date = re.fullmatch(rf"تا\s*({CURRENT})\s*(\d{{4}})\s+({MONTH_PATTERN})", text, re.I)
    if reversed_date:
        text = f"{reversed_date[3]} {reversed_date[2]} تا {reversed_date[1]}"
    match = RANGE.fullmatch(text)
    if not match:
        result["error_code"] = "date_unrecognized"
        return result
    try:
        a, b, pa, ya = endpoint(match["start"], reference)
        c, d, pb, yb = endpoint(match["end"], reference)
        if d < a or a > reference or c > reference or (d - a).days > 40 * 366:
            raise ValueError("invalid_chronology")
        result.update(
            status="valid",
            ongoing=bool(re.fullmatch(CURRENT, match["end"], re.I)),
            start=dict(
                earliest=a.isoformat(),
                latest=min(b, reference).isoformat(),
                precision=pa,
                year=ya,
                calendar="jalali" if ya and ya < 1500 else "gregorian",
            ),
            end=dict(
                earliest=c.isoformat(),
                latest=min(d, reference).isoformat(),
                precision=pb,
                year=yb,
                calendar="jalali" if yb and yb < 1500 else "gregorian",
            ),
        )
    except (ValueError, TypeError, OverflowError) as error:
        result.update(
            status="invalid", error_code="invalid_chronology" if str(error) == "invalid_chronology" else "invalid_date"
        )
    return result


def union_years(intervals):
    merged = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    return round(sum((b - a).days for a, b in merged) / 365.2425, 3)


def totals(records):
    output = {}
    for kind in ["employment", "internship", "freelance", "volunteering", "total_work"]:
        lower, upper = [], []
        for record in records:
            if record["kind"] != kind and not (
                kind == "total_work" and record["kind"] in {"employment", "internship", "freelance"}
            ):
                continue
            dates = record["dates"]
            if dates["status"] != "valid":
                continue
            a, b = [date.fromisoformat(dates["start"][k]) for k in ("earliest", "latest")]
            c, d = [date.fromisoformat(dates["end"][k]) for k in ("earliest", "latest")]
            lower.append((b, c))
            upper.append((a, d))
        output[kind] = dict(min_years=union_years(lower), max_years=union_years(upper), basis="source_date_bounds")
    return output
