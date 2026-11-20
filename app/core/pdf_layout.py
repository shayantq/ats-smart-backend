"""استخراج صفحه‌ای با شاهد هندسی؛ بدون لاگ‌کردن محتوای سند."""

import hashlib
import math
import re
import time
import unicodedata
from collections import Counter, defaultdict
from statistics import mean

import fitz
import pytesseract
from PIL import Image

from app.core.config import settings
from app.core.resume_dates import normalize as normalize_date
from app.core.resume_sections import annotate, heading, normalize

EXTRACTION_VERSION = 3


def rect(values):
    return [round(float(v), 3) for v in values]


def word_text(words):
    """ترتیب مکانی کلمات؛ ترتیب عبارت انگلیسی داخل خط فارسی حفظ می‌شود."""
    rtl = sum(len(re.findall(r"[\u0600-\u06ff]", unicodedata.normalize("NFKC", w["text"]))) for w in words) > sum(
        len(re.findall(r"[a-zA-Z]", w["text"])) for w in words
    )
    ordered = sorted(words, key=lambda w: w["bbox"][0], reverse=rtl)
    if rtl:
        i = 0
        while i < len(ordered):
            if re.search(r"[a-zA-Z0-9]", ordered[i]["text"]):
                j = i + 1
                while j < len(ordered) and re.search(r"[a-zA-Z0-9]", ordered[j]["text"]):
                    j += 1
                ordered[i:j] = reversed(ordered[i:j])
                i = j
            else:
                i += 1
    return " ".join(unicodedata.normalize("NFKC", w["text"]) for w in ordered).strip()


def lines_from_words(groups, page_number, width):
    result = []
    for words in groups.values():
        words.sort(key=lambda w: w["bbox"][0])
        runs = [[]]
        for word in words:
            # شکاف بزرگ میان دو ستون نباید به یک خط جعلی تبدیل شود.
            if runs[-1] and word["bbox"][0] - runs[-1][-1]["bbox"][2] > max(width * 0.08, 32):
                runs.append([])
            runs[-1].append(word)
        for run in runs:
            box = [
                min(w["bbox"][0] for w in run),
                min(w["bbox"][1] for w in run),
                max(w["bbox"][2] for w in run),
                max(w["bbox"][3] for w in run),
            ]
            text = word_text(run)
            if text:
                confidences = [w["confidence"] for w in run if w["confidence"] is not None]
                style = run[0].get("native_style")
                result.append(
                    dict(
                        id=f"p{page_number}-l{len(result)+1}",
                        page=page_number,
                        bbox=rect(box),
                        text=text,
                        source_text=" ".join(w["text"] for w in run),
                        words=run,
                        method=run[0]["method"],
                        ocr_confidence=mean(confidences) if confidences else None,
                        **({"native_style": style} if style else {}),
                    )
                )
    return result


def native_words(page):
    groups = defaultdict(list)
    textpage = page.get_textpage(flags=fitz.TEXTFLAGS_WORDS)
    styles = {}
    for block in page.get_text("dict", textpage=textpage)["blocks"]:
        for i, line in enumerate(block.get("lines", [])):
            spans = [span for span in line["spans"] if any(c.isalnum() for c in span["text"])]
            if spans:
                dominant = max(spans, key=lambda span: sum(c.isalnum() for c in span["text"]))
                styles[(block["number"], i)] = dict(
                    size=round(dominant["size"], 1), bold=bool(dominant["flags"] & fitz.TEXT_FONT_BOLD)
                )
    for x0, y0, x1, y1, text, bno, lno, _ in page.get_text("words", textpage=textpage):
        if text.strip():
            groups[(bno, lno)].append(
                dict(
                    text=text,
                    bbox=rect((x0, y0, x1, y1)),
                    method="native",
                    confidence=None,
                    native_style=styles.get((bno, lno)),
                )
            )
    return groups


def ocr_words(page, clip, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("extraction_budget_exceeded")
    zoom = min(300 / 72, math.sqrt(16_000_000 / max(clip.width * clip.height, 1)))
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False, colorspace=fitz.csRGB)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    try:
        data = pytesseract.image_to_data(
            image,
            lang=settings.OCR_LANGUAGES,
            output_type=pytesseract.Output.DICT,
            timeout=min(30, remaining),
            config="--psm 3",
        )
    finally:
        image.close()
    groups = defaultdict(list)
    for i, text in enumerate(data["text"]):
        if not text.strip() or float(data["conf"][i]) < 0:
            continue
        x, y = data["left"][i], data["top"][i]
        box = [
            clip.x0 + x / zoom,
            clip.y0 + y / zoom,
            clip.x0 + (x + data["width"][i]) / zoom,
            clip.y0 + (y + data["height"][i]) / zoom,
        ]
        groups[(data["block_num"][i], data["par_num"][i], data["line_num"][i])].append(
            dict(text=text, bbox=rect(box), method="ocr", confidence=float(data["conf"][i]))
        )
    return groups


def reading_order(blocks, width):
    narrow = [b for b in blocks if b["bbox"][2] - b["bbox"][0] < width * 0.65]
    candidates = []
    for left in narrow:
        for right in narrow:
            gap = right["bbox"][0] - left["bbox"][2]
            cut = (left["bbox"][2] + right["bbox"][0]) / 2
            if gap < 16 or not width * 0.2 < cut < width * 0.8:
                continue
            left_count = sum(b["bbox"][2] <= cut for b in narrow)
            right_count = sum(b["bbox"][0] >= cut for b in narrow)
            crossing = len(narrow) - left_count - right_count
            aligned_rows = sum(
                any(a["bbox"][1] < b["bbox"][3] and b["bbox"][1] < a["bbox"][3] for b in narrow if b["bbox"][0] >= cut)
                for a in narrow
                if a["bbox"][2] <= cut
            )
            if min(left_count, right_count) >= 3 and crossing <= len(narrow) * 0.1 and aligned_rows >= 2:
                candidates.append((min(left_count, right_count), gap, cut))
    cut = max(candidates)[2] if candidates else None
    # شکاف سراسری کلمات از شکاف یک خط قابل اعتمادتر است؛ سربرگ عریض در آن دخالت نمی‌کند.
    if blocks:
        top = min(b["bbox"][1] for b in blocks)
        bottom = max(b["bbox"][3] for b in blocks)
        body = [
            w
            for b in blocks
            if top + (bottom - top) * 0.13 < b["bbox"][1] < bottom - (bottom - top) * 0.04
            for w in b["words"]
        ]
        gutters = []
        for point in range(int(width * 0.25), int(width * 0.82), 2):
            left = [w for w in body if w["bbox"][2] <= point]
            right = [w for w in body if w["bbox"][0] >= point]
            if len(left) < 8 or len(right) < 8 or len(left) + len(right) != len(body):
                continue
            gap = min(w["bbox"][0] for w in right) - max(w["bbox"][2] for w in left)
            coincident = sum(
                any(a["bbox"][1] < b["bbox"][3] and b["bbox"][1] < a["bbox"][3] for b in right) for a in left
            )
            if gap > width * 0.015 and coincident >= 3:
                gutters.append((gap, min(len(left), len(right)), point))
        if gutters:
            cut = max(gutters)[2]
    if cut is not None:
        right_lines = [b["text"] for b in narrow if b["bbox"][0] >= cut]
        if right_lines and sum(bool(re.match(r"^\d{2,4}[/.-]", text)) for text in right_lines) / len(right_lines) > 0.8:
            # تاریخ‌های راست‌چین کنار سمت‌ها، ستون مستقل خواندن نیستند.
            cut = None
    rtl = sum(len(re.findall(r"[\u0600-\u06ff]", b["text"])) for b in blocks) > sum(
        len(re.findall(r"[a-zA-Z]", b["text"])) for b in blocks
    )
    for block in blocks:
        block["column"] = 0 if cut is None or (block["bbox"][0] + block["bbox"][2]) / 2 < cut else 1
    if cut is None:
        return sorted(blocks, key=lambda b: (round(b["bbox"][1] / 3), b["bbox"][0])), "single"
    # خطوط سرتاسری، مرز نوار خواندن‌اند؛ ستون‌ها در هر نوار جدا خوانده می‌شوند.
    spanning = sorted([b for b in blocks if b["bbox"][0] < cut < b["bbox"][2]], key=lambda b: b["bbox"][1])
    ordinary = [b for b in blocks if b not in spanning]
    result = []
    for boundary in spanning + [None]:
        band = [b for b in ordinary if boundary is None or b["bbox"][1] < boundary["bbox"][1]]
        result.extend(sorted(band, key=lambda b: ((-b["column"] if rtl else b["column"]), b["bbox"][1])))
        ordinary = [b for b in ordinary if b not in band]
        if boundary:
            boundary["column"] = -1
            result.append(boundary)
    return result, "columns"


def connect_lines(blocks):
    """اتصال عنوان شکسته و ثبت گروه پاراگراف بدون حذف خطوط شاهد."""
    result = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if i + 1 < len(blocks):
            following = blocks[i + 1]
            gap = following["bbox"][1] - block["bbox"][3]
            joined = block["text"] + " " + following["text"]
            if (
                not heading(block["text"])
                and heading(joined)
                and block["column"] == following["column"]
                and -2 <= gap <= 20
            ):
                block = dict(
                    block,
                    text=joined,
                    source_text=block["source_text"] + "\n" + following["source_text"],
                    bbox=rect(fitz.Rect(block["bbox"]) | fitz.Rect(following["bbox"])),
                    words=block["words"] + following["words"],
                    joined_line_ids=[block["id"], following["id"]],
                )
                i += 1
        result.append(block)
        i += 1
    annotate(result)
    for i, block in enumerate(result):
        block["paragraph_id"] = block["id"]
        if i and not block["is_heading"] and not result[i - 1]["is_heading"]:
            previous = result[i - 1]
            gap = block["bbox"][1] - previous["bbox"][3]
            if (
                block["column"] == previous["column"]
                and block["section"] == previous["section"]
                and 0 <= gap <= max(8, block["bbox"][3] - block["bbox"][1])
                and abs(block["bbox"][0] - previous["bbox"][0]) < 20
            ):
                block["paragraph_id"] = previous["paragraph_id"]
    return result


def record_in_margin(block, next_blocks):
    if not (block.get("native_style") or {}).get("bold"):
        return False
    # عنوانِ تکراری که زیر آن تاریخ رکورد دیگری آمده جزو محتوای اصلی است.
    return any(
        other["column"] == block["column"]
        and 0 <= other["bbox"][1] - block["bbox"][1] <= 84
        and re.search(r"\b(?:13|14|19|20)\d{2}\b", normalize_date(other["text"]))
        for other in next_blocks[:4]
    )


def extract_pdf(content):
    try:
        document = fitz.open(stream=content, filetype="pdf")
    except Exception:
        raise ValueError("invalid_pdf") from None
    pages, warnings = [], []
    deadline = time.monotonic() + 180
    with document:
        if document.needs_pass:
            raise ValueError("encrypted_pdf")
        for index, page in enumerate(document):
            rotation = page.rotation
            # مختصات در فضای crop با rotation صفر گزارش می‌شوند؛ فایل ورودی تغییر نمی‌کند.
            page.set_rotation(0)
            box = page.rect
            groups = native_words(page)
            native = [w for group in groups.values() for w in group]
            blocks = lines_from_words(groups, index + 1, box.width)
            page_warnings = []
            useful = any(re.search(r"[\w\u0600-\u06ff]", w["text"]) for w in native)
            clips = []
            if not useful:
                clips = [box]
            else:
                for image in page.get_image_info():
                    area = fitz.Rect(image["bbox"]) & box
                    if area.is_empty:
                        continue
                    if area.get_area() < box.get_area() * 0.025:
                        page_warnings.append("small_image_not_ocr")
                        continue
                    inside = [w for w in native if area.contains(fitz.Rect(w["bbox"]))]
                    if len(inside) < 40:
                        clips.append(area)
            regions = []
            for clip in clips:
                region = dict(bbox=rect(clip), status="pending")
                regions.append(region)
                tick = time.perf_counter()
                try:
                    ocr = ocr_words(page, clip, deadline)
                    for group in ocr.values():
                        # متن قابل خواندن لایهٔ PDF با OCR دوباره‌شماری نمی‌شود.
                        group[:] = [
                            w
                            for w in group
                            if not any(
                                normalize(w["text"]) == normalize(n["text"])
                                and (fitz.Rect(w["bbox"]) & fitz.Rect(n["bbox"])).get_area()
                                > min(fitz.Rect(w["bbox"]).get_area(), fitz.Rect(n["bbox"]).get_area()) * 0.4
                                for n in native
                            )
                        ]
                    groups_ocr = {k: v for k, v in ocr.items() if v}
                    extra = lines_from_words(groups_ocr, index + 1, box.width)
                    region["status"] = "completed" if extra else "no_text_detected"
                    for b in extra:
                        b["id"] = f"p{index+1}-o{len(blocks)+1}"
                        blocks.append(b)
                except (RuntimeError, OSError, TimeoutError):
                    region["status"] = "failed"
                    page_warnings.append("ocr_region_failed")
                finally:
                    region["elapsed_ms"] = (time.perf_counter() - tick) * 1000
            blocks, layout = reading_order(blocks, box.width)
            tables = []
            if native:
                try:
                    for table in page.find_tables().tables:
                        tables.append(
                            dict(
                                bbox=rect(table.bbox),
                                rows=table.row_count,
                                columns=table.col_count,
                                cells=[rect(cell) if cell else None for cell in table.cells],
                            )
                        )
                except Exception:
                    page_warnings.append("table_detection_unavailable")
            for table_index, table in enumerate(tables):
                area = fitz.Rect(table["bbox"])
                members = [b for b in blocks if area.contains(fitz.Rect(b["bbox"][:2], b["bbox"][2:]))]
                if members:
                    first = min(blocks.index(b) for b in members)
                    blocks = [b for b in blocks if b not in members]
                    members.sort(key=lambda b: (round(b["bbox"][1] / 3), b["bbox"][0]))
                    for member in members:
                        member["table"] = table_index
                    blocks[first:first] = members
            if not blocks:
                page_warnings.append("blank_or_unreadable_page")
            if any(b["ocr_confidence"] is not None and b["ocr_confidence"] < 70 for b in blocks):
                page_warnings.append("low_ocr_confidence")
            blocks = connect_lines(blocks)
            pages.append(
                dict(
                    number=index + 1,
                    width=box.width,
                    height=box.height,
                    original_rotation=rotation,
                    cropbox=rect(page.cropbox),
                    coordinate_space="unrotated_crop_points",
                    layout=layout,
                    blocks=blocks,
                    tables=tables,
                    ocr_regions=regions,
                    extraction_method="mixed" if native and clips else "native" if native else "ocr",
                    warnings=sorted(set(page_warnings)),
                )
            )
    # تکرارِ فقط حاشیه‌ها حذف می‌شود؛ شاهد و نسخهٔ اول همچنان باقی می‌مانند.
    margins = Counter(
        key
        for p in pages
        for key in {
            normalize(b["text"])
            for b in p["blocks"]
            if b["bbox"][1] < p["height"] * 0.06 or b["bbox"][3] > p["height"] * 0.94
        }
    )
    seen_pages, seen_margins = {}, set()
    for p in pages:
        fingerprint = hashlib.sha256("\n".join(b["text"] for b in p["blocks"]).encode()).hexdigest()
        if p["blocks"] and fingerprint in seen_pages:
            p["duplicate_of"] = seen_pages[fingerprint]
            p["warnings"].append("duplicate_page")
        else:
            seen_pages[fingerprint] = p["number"]
        for i, b in enumerate(p["blocks"]):
            key = normalize(b["text"])
            margin = b["bbox"][1] < p["height"] * 0.06 or b["bbox"][3] > p["height"] * 0.94
            if p.get("duplicate_of"):
                b["excluded_reason"] = "duplicate_page"
            elif (
                margin
                and not heading(b["text"])
                and margins[key] > 1
                and not record_in_margin(b, p["blocks"][i + 1 : i + 5])
            ):
                if key in seen_margins:
                    b["excluded_reason"] = "repeated_margin"
                seen_margins.add(key)
            if b["bbox"][1] > p["height"] * 0.9 and re.match(r"powered\s*by\b", key):
                b["excluded_reason"] = "generator_footer"
        warnings.extend(p["warnings"])
    raw = "\n\n".join("\n".join(b["text"] for b in p["blocks"] if not b.get("excluded_reason")) for p in pages).strip()
    if not raw:
        raise ValueError("no_readable_text")
    return dict(
        version=EXTRACTION_VERSION,
        file_sha256=hashlib.sha256(content).hexdigest(),
        raw_text=raw,
        pages=pages,
        warnings=sorted(set(warnings)),
        status="partial" if any("failed" in w or "unreadable" in w for w in warnings) else "completed",
    )
