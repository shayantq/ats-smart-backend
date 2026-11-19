from dataclasses import dataclass
from fnmatch import fnmatchcase
from operator import attrgetter
from typing import Iterable
from unicodedata import category

ICON_FONTS = ("fontello*", "fontawesome*", "icon*")
_BIDI = {*range(0x202A, 0x202F), *range(0x2066, 0x206A), 0x200E, 0x200F}


@dataclass(frozen=True)
class PageSpan:
    page: int
    text: str
    block_id: str | None = None
    bbox: tuple[float, ...] | None = None
    font: str | None = None
    start: int = 0


@dataclass(frozen=True)
class Origin:
    page: int
    block_id: str | None
    bbox: tuple[float, ...] | None
    offset: int
    span_offset: int
    codepoint: int


@dataclass(frozen=True)
class NormalizedResume:
    text: str
    origins: tuple[Origin, ...]
    removed: tuple[tuple[str, Origin], ...]
    removals: dict[str, int]
    pages: tuple[int, ...]

    def restore_original(self) -> str:
        origins = (*self.origins, *(origin for _, origin in self.removed))
        return "".join(chr(origin.codepoint) for origin in sorted(origins, key=attrgetter("offset")))


def normalize_spans(spans: Iterable[PageSpan], *, icon_fonts: tuple[str, ...] = ICON_FONTS) -> NormalizedResume:
    kept, origins, removed, pages = [], [], [], {}
    counts = dict(bidi=0, icon=0, spaces=0, private_use_kept=0)
    offset = 0
    previous_space = False
    for span in spans:
        pages[span.page] = None
        font = (span.font or "").rsplit("+", 1)[-1].casefold()
        icon_font = bool(font) and any(fnmatchcase(font, pattern.casefold()) for pattern in icon_fonts)
        for index, char in enumerate(span.text):
            codepoint = ord(char)
            origin = Origin(span.page, span.block_id, span.bbox, offset, span.start + index, codepoint)
            offset += 1
            private = category(char) == "Co"
            reason = None
            if codepoint in _BIDI:
                reason = "bidi"
            elif private and icon_font:
                reason = "icon"
            elif char == " " and previous_space:
                reason = "spaces"
            if reason:
                counts[reason] += 1
                removed.append((reason, origin))
                continue
            counts["private_use_kept"] += int(private)
            kept.append(char)
            origins.append(origin)
            previous_space = char == " "
    return NormalizedResume("".join(kept), tuple(origins), tuple(removed), counts, tuple(pages))


def spans_from_extraction(raw: str, layout: dict | None) -> tuple[list[PageSpan], int, int]:
    spans = []
    pages = (layout or {}).get("pages") or []
    excluded = 0
    for index, page in enumerate(pages):
        number = page["number"]
        spans.append(PageSpan(number, ""))
        previous = False
        for block in page.get("blocks", []):
            if block.get("excluded_reason"):
                excluded += len(block["text"])
                continue
            if previous:
                spans.append(PageSpan(number, "\n"))
            previous = True
            bbox = block.get("bbox")
            spans.append(
                PageSpan(number, block["text"], block.get("id"), tuple(bbox) if bbox else None, block.get("font"))
            )
        if index + 1 < len(pages):
            spans.append(PageSpan(number, "\n\n"))
    joined = "".join(span.text for span in spans)
    if spans and joined == raw:
        return spans, 0, excluded
    if not spans or joined.strip() != raw:
        return [PageSpan(0, raw)], 1, excluded
    begin, end = len(joined) - len(joined.lstrip()), len(joined.rstrip())
    offset = 0
    trimmed = []
    for span in spans:
        start, stop = max(0, begin - offset), min(len(span.text), end - offset)
        trimmed.append(
            PageSpan(span.page, span.text[start:stop], span.block_id, span.bbox, span.font, start)
            if start < stop
            else PageSpan(span.page, "")
        )
        offset += len(span.text)
    return trimmed, 0, excluded
