import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Callable
from unicodedata import name

from app.core.resume_dates import normalize
from app.core.resume_sections import heading
from app.core.structured_resume import ACTION, EMAIL, PHONE, URL
from app.model_inference.budget import PromptBudget, configured_tokenizer_sha256
from app.model_inference.resume_normalization import ICON_FONTS, normalize_spans, spans_from_extraction

BUILDER_VERSION = 3
_CAP_ALGORITHM_VERSION = 1
_LEVELS = {"digest_l0": 0, "digest_l1": 1, "digest_l2": 2}
_SECTIONS = {
    "education": "education",
    "certifications": "certificate",
    "languages": "language",
    "publications": "publication",
    "awards": "honor",
}
_MARKER_OPENINGS = ("[مرجع ", "[شرح مطابق مرجع ", "[حذف ")
_AUDIENCE = re.compile(
    r"\b(?:audience|participants|attendees|students|learners|for|to)\b|مخاطب|شرکت.کنند|دانشجو|برای", re.I
)
_BULLET = re.compile(r"^(?:[•●▪*¢-]|e\s)\s*")
_SENTENCE_END = re.compile(r"[.!?؟]+(?=\s|$)")


def cache_key(
    mode: str, *, cap: int | None, icon_fonts: tuple[str, ...], context: int, output: int, tokenizer: str
) -> str:
    if mode == "raw":
        return "raw"
    level = digest_level(mode)
    identity = [icon_fonts]
    if level == 2:
        identity += [cap, context, output, configured_tokenizer_sha256(tokenizer)]
    digest = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    return f"{mode}:{level}:{BUILDER_VERSION}-cap{_CAP_ALGORITHM_VERSION}:{digest}"


def digest_level(mode: str) -> int:
    return _LEVELS[mode]


def iter_records(structured: dict):
    for record in structured.get("activities") or []:
        yield record["id"], record["kind"], record
    for section, kind in _SECTIONS.items():
        for index, record in enumerate(structured.get(section) or [], 1):
            yield f"{kind}-{index}", kind, record


def _value(fact: dict) -> str:
    return fact.get("value") or ""


@dataclass(frozen=True)
class _Line:
    start: int
    end: int
    page: int
    block: str | None
    text: str
    label: str | None


def _lines(document, raw: str) -> list[_Line]:
    result = []
    start = original_start = 0
    for normalized in document.text.splitlines(keepends=True):
        end = start + len(normalized)
        origin = document.origins[start]
        original_end = len(raw) if end == len(document.text) else document.origins[end - 1].offset + 1
        original = raw[original_start:original_end]
        label = heading(original) if len(original.splitlines()) == 1 else None
        result.append(_Line(start, end, origin.page, origin.block_id, normalized, label))
        start = end
        original_start = original_end
    return result


def _matches(line: _Line, fact: dict, *, whole: bool = False) -> bool:
    value, source = normalize(_value(fact)), normalize(line.text)
    if not value or not (value == source if whole else value in source):
        return False
    refs = {
        (ref["page"], ref["block_id"]) for ref in fact.get("evidence") or [] if ref.get("block_id") and ref.get("page")
    }
    return not refs or line.page == 0 or (line.page, line.block) in refs


def _attribute(lines, structured):
    records = list(iter_records(structured))
    owners = {}
    descriptions = []
    protected = set()
    anchors = {}
    kinds = {}
    candidates = []
    source_lines = [normalize(line.text) if not line.label else None for line in lines]
    active = [(i, source) for i, source in enumerate(source_lines) if source or source is None]
    block_lines = {}
    for i, line in enumerate(lines):
        if line.block and not line.label:
            block_lines.setdefault((line.page, line.block), []).append(i)

    def source_ranges(ref):
        block = block_lines.get((ref.get("page"), ref.get("block_id")))
        if block:
            return [(block[0], block[-1])]
        parts = [source for value in ref.get("text", "").splitlines() if (source := normalize(value))]
        size = len(parts)
        return (
            [
                (active[i][0], active[i + size - 1][0])
                for i in range(len(active) - size + 1)
                if [source for _, source in active[i : i + size]] == parts
            ]
            if size
            else []
        )

    for record_id, kind, record in records:
        fields = record.get("fields") or {}
        unique = set()
        title_ranges = set()
        for field, fact in fields.items():
            if not _value(fact):
                continue
            matches = {bounds for ref in fact.get("evidence") or [] for bounds in source_ranges(ref)}
            if len(matches) == 1:
                unique.update(matches)
            if field in {"job_title", "project_name", "title", "language"}:
                title_ranges.update(matches)
            protected.update(i for first, last in matches for i in range(first, last + 1) if _matches(lines[i], fact))
        if unique:
            candidates.append((min(first for first, _ in unique), title_ranges, (record_id, kind, record)))

    last_start = -1
    for start, ranges, record in sorted(candidates, key=lambda item: item[0]):
        preceding = [
            first
            for first, last in ranges
            if last_start < first <= start
            and last <= start
            and not any(line.label for line in lines[first : start + 1])
        ]
        anchor = preceding[0] if len(preceding) == 1 else start
        anchors.setdefault(anchor, []).append(record)
        last_start = start

    start = None
    kept = []
    for i, line in enumerate(lines):
        if line.label or i in anchors:
            start = None
        if i in anchors and len(anchors[i]) == 1:
            start = anchors[i][0]
            kept.append(start[0])
            kinds[start[0]] = start[1]
            owners[i] = start[0]
        if start is None or line.label:
            continue
        record_id, _, record = start
        if i in anchors or any(_matches(line, fact) for fact in (record.get("fields") or {}).values()):
            owners[i] = record_id
        elif any(_matches(line, fact, whole=True) for fact in record.get("claims") or []):
            owners[i] = record_id
            content = _BULLET.sub("", line.text.strip())
            if i not in protected and ACTION.search(content) and not _AUDIENCE.search(content):
                if descriptions and descriptions[-1][0] == record_id and descriptions[-1][2] == i - 1:
                    _, first, _ = descriptions[-1]
                    descriptions[-1] = (record_id, first, i)
                else:
                    descriptions.append((record_id, i, i))
    unresolved = [record_id for record_id, _, _ in records if record_id not in kinds]
    return owners, descriptions, protected, (*kept, *unresolved), kinds, len(unresolved)


def _script(text: str) -> int:
    scripts = {name(char, "").split(" ", 1)[0] for char in text if char.isalpha()}
    mask = int("ARABIC" in scripts) | (2 * int("LATIN" in scripts))
    return mask | (4 * int(bool(scripts - {"ARABIC", "LATIN"})))


def _coverage(document, lines, owners) -> dict:
    pages = {page: dict(assigned=0, layout=0, unassigned=0, characters=0) for page in document.pages}
    spans = []
    for i, line in enumerate(lines):
        category = "layout" if line.label else "assigned" if i in owners else "unassigned"
        for origin in document.origins[line.start : line.end]:
            pages[origin.page][category] += 1
            pages[origin.page]["characters"] += 1
        if category == "unassigned":
            for offset in range(line.start, line.end):
                page = document.origins[offset].page
                if spans and spans[-1][0] == page and spans[-1][2] == offset:
                    spans[-1][2] += 1
                else:
                    spans.append([page, offset, offset + 1])
    total = {
        key: sum(page[key] for page in pages.values()) for key in ("assigned", "layout", "unassigned", "characters")
    }
    return {
        **total,
        "coverage_pct": 100 * (total["assigned"] + total["layout"]) / total["characters"] if total["characters"] else 0,
        "pages": pages,
        "unassigned_spans": [
            dict(page=page, start=start, end=end, length=end - start, script=_script(document.text[start:end]))
            for page, start, end in spans
        ],
    }


@dataclass(frozen=True)
class Edit:
    start: int
    end: int
    original: str
    replacement: str
    record_id: str | None = None


@dataclass(frozen=True)
class Digest:
    level: int
    text: str
    budget: PromptBudget
    coverage: dict
    record_ids: tuple[str, ...]
    omitted_by_record: dict[str, int]
    unassigned_carried: int
    unassigned_omitted: int
    retained_pct: float
    edits: tuple[Edit, ...]
    cap_used: int | None

    def restore_normalized(self) -> str:
        text = self.text
        for edit in self.edits:
            text = text[: edit.start] + edit.original + text[edit.start + len(edit.replacement) :]
        return text


def _render(text, edits):
    pieces, last = [], 0
    for edit in edits:
        pieces.extend((text[last : edit.start], edit.replacement))
        last = edit.end
    return "".join((*pieces, text[last:]))


class ResumeDigestBuilder:
    def __init__(self, raw: str, structured: dict, layout: dict | None, *, icon_fonts: tuple[str, ...] = ICON_FONTS):
        spans, fallback, upstream_excluded = spans_from_extraction(raw, layout)
        self.normalized = normalize_spans(spans, icon_fonts=icon_fonts)
        self.marker_collision = any(marker in self.normalized.text for marker in _MARKER_OPENINGS)
        self.lines = _lines(self.normalized, raw)
        owners, self.descriptions, protected, kept, self.kinds, unanchored = _attribute(self.lines, structured)
        self.kept = tuple(kept)
        self.coverage = {
            **_coverage(self.normalized, self.lines, owners),
            "layout_fallback": fallback,
            "upstream_excluded_chars": upstream_excluded,
            "unanchored_records": unanchored,
            "ambiguous_attribution": unanchored,
            "normalization": self.normalized.removals,
        }
        self.unassigned = []
        identity = [
            *((structured.get("identity") or {}).values()),
            *(structured.get("contacts") or []),
            *(structured.get("links") or []),
        ]
        for i, line in enumerate(self.lines):
            if (
                not line.label
                and i not in owners
                and i not in protected
                and line.text.strip()
                and not _AUDIENCE.search(line.text)
                and not any(pattern.search(line.text) for pattern in (EMAIL, PHONE, URL))
                and not any(_matches(line, fact) for fact in identity)
            ):
                if self.unassigned and self.unassigned[-1][2] == i - 1 and self.lines[i - 1].page == line.page:
                    _, first, _ = self.unassigned[-1]
                    self.unassigned[-1] = (None, first, i)
                else:
                    self.unassigned.append((None, i, i))

    def _item(self, record, first, last):
        text = self.normalized.text
        start, end = self.lines[first].start, self.lines[last].end
        body = text[start:end].rstrip("\r\n")
        return start, body, record

    def _description_edits(self):
        seen, referenced = {}, set()
        edits = []
        for record, first, last in self.descriptions:
            start, body, _ = self._item(record, first, last)
            if first != last:
                key = (self.kinds[record], body)
                source = seen.setdefault(key, (record, start, len(seen) + 1))
                prior_record, prior_start, marker = source
                if prior_record != record:
                    if marker not in referenced:
                        edits.append(Edit(prior_start, prior_start, "", f"[مرجع {marker}]\n"))
                        referenced.add(marker)
                    edits.append(Edit(start, start + len(body), body, f"[شرح مطابق مرجع {marker}]", record))
        return edits

    def _shared_cap(self, measure, cap):
        text = self.normalized.text
        sources = [self._item(*item) for item in (*self.descriptions, *self.unassigned)]
        if cap is None:
            cap = max((len(body) for _, body, _ in sources), default=0)
        items = []
        candidates = {0, cap}
        for start, body, record in sources:
            ends = [match.end() for match in _SENTENCE_END.finditer(body)]
            items.append((start, body, record, ends))
            candidates.update(end - 1 for end in (*ends, len(body)) if 0 < end <= cap)

        def evaluate(limit):
            edits = []
            for start, body, record, ends in items:
                if len(body) <= limit:
                    continue
                cut = max((end for end in ends if end <= limit), default=0)
                tail = body[cut:]
                label = "از شرح" if record is not None else "بدون انتساب"
                edits.append(Edit(start + cut, start + len(body), tail, f" [حذف {len(tail)} نویسهٔ {label}]", record))
            edits.sort(key=lambda edit: edit.start)
            output = _render(text, edits)
            return output, measure(output), edits, limit

        low = evaluate(0)
        if low[1].over_by or not cap:
            return low
        high = evaluate(cap)
        if not high[1].over_by:
            return high
        left, right = 0, cap
        while right - left > 1:
            middle = (left + right) // 2
            result = evaluate(middle)
            if result[1].over_by:
                right = middle
            else:
                left, low = middle, result
        # هزینهٔ توکن نشانه‌ها و مرز BPE می‌تواند با افزایش سقف کاهش پیدا کند.
        for limit in sorted((value for value in candidates if left < value < cap), reverse=True):
            result = evaluate(limit)
            if not result[1].over_by:
                return result
        return low

    def build(self, level: int, measure: Callable[[str], PromptBudget], *, cap: int | None = None) -> Digest | None:
        if self.marker_collision:
            return None
        cap_used = None
        if level == 2:
            output, budget, edits, cap_used = self._shared_cap(measure, cap)
        else:
            edits = sorted(self._description_edits(), key=lambda edit: edit.start) if level == 1 else []
            output = _render(self.normalized.text, edits)
            budget = measure(output)
        removed = Counter()
        omitted = 0
        for edit in edits:
            if edit.record_id is not None:
                removed[edit.record_id] += edit.end - edit.start
            else:
                omitted += edit.end - edit.start
        size = len(self.normalized.text)
        return Digest(
            level,
            output,
            budget,
            self.coverage,
            self.kept,
            dict(removed),
            self.coverage["unassigned"] - omitted,
            omitted,
            100 * (size - omitted - sum(removed.values())) / size if size else 100,
            tuple(edits),
            cap_used,
        )
