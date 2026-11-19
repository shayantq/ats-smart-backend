import json
import os
from datetime import date
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.structured_resume import build_structured
from app.model_inference.budget import PromptBudget
from app.model_inference.resume_digest import ResumeDigestBuilder, cache_key
from app.model_inference.resume_normalization import PageSpan, normalize_spans
from dev.resume_digest_measure import _distribution, measure_sample
from dev.resume_record_score import HumanReference, score_records


def test_normalization_preserves_technical_terms_and_offsets():
    text = "C++  C# .NET ASP.NET Core Node.js داده‌های \u202bآزمایشی\u202c\n\u200e۰۱۲/۴-۵\u200f"
    original = [PageSpan(1, text, "a", (1, 2, 3, 4)), PageSpan(2, "\ue001", "b", font="AA+FontAwesome")]
    original.append(PageSpan(2, "\ue001\ue002", "c", font="Silicon Serif"))
    result = normalize_spans(original)
    assert result.text == "C++ C# .NET ASP.NET Core Node.js داده‌های آزمایشی\n۰۱۲/۴-۵\ue001\ue002"
    assert result.removals == {"spaces": 1, "bidi": 4, "icon": 1, "private_use_kept": 2}
    assert result.restore_original() == "".join(span.text for span in original)
    raw = result.restore_original()
    spans_by_id = {span.block_id: span for span in original}
    for char, origin in zip(result.text, result.origins, strict=True):
        span = spans_by_id[origin.block_id]
        assert char == raw[origin.offset] == span.text[origin.span_offset] == chr(origin.codepoint)
        assert (origin.page, origin.bbox) == (span.page, span.bbox)
    assert normalize_spans([PageSpan(1, "\ue001", font="SymbolPack")], icon_fonts=("symbol*",)).text == ""


def _document():
    first = "Built synthetic components. Implemented independent verification with generated data."
    second = "Designed synthetic pipelines. Measured reproducibility with independent fixtures."
    record_lines = [
        ["Software Engineer | Example Systems 01/2020 - 12/2021", "Audience: synthetic lab group", first, second],
        ["Data Engineer | Fixture Labs 01/2022 - 12/2023", "Audience: synthetic test group", first, second],
    ]
    pages = [
        ["Synthetic Example", "Experience", *record_lines[0]],
        [*record_lines[1], "Interests", "Unassigned demonstration data. " * 60],
    ]
    layout = {
        "pages": [
            {
                "number": page,
                "blocks": [
                    {"id": f"{page}-{index}", "bbox": [1, index * 10, 100, index * 10 + 5], "text": text}
                    for index, text in enumerate(lines)
                ],
            }
            for page, lines in enumerate(pages, 1)
        ]
    }
    raw = "\n\n".join("\n".join(page) for page in pages).strip()
    layout["pages"][1]["blocks"][-1]["text"] = layout["pages"][1]["blocks"][-1]["text"].rstrip()
    structured = build_structured(raw, layout, reference=date(2026, 1, 1))
    return raw, layout, structured, first, second, record_lines


def test_digest_levels_reconcile_coverage_preserve_records_and_reverse_edits():
    raw, layout, structured, first, second, record_lines = _document()
    builder = ResumeDigestBuilder(raw, structured, layout)

    def measure(text, limit=6000):
        return PromptBudget(len(text), 0, limit, "estimate")

    l0, l1, l2 = [builder.build(level, measure, cap=35) for level in range(3)]
    assert l0.text == builder.normalized.text == builder.normalized.restore_original() == raw
    assert l0.edits == ()
    assert l0.coverage["layout_fallback"] == 0
    assert set(l0.coverage["pages"]) == {1, 2}
    for page in (*l0.coverage["pages"].values(), l0.coverage):
        assert page["assigned"] + page["layout"] + page["unassigned"] == page["characters"]
    assert sum(span["length"] for span in l0.coverage["unassigned_spans"]) == l0.coverage["unassigned"]
    assert all(set(span) == {"page", "start", "end", "length", "script"} for span in l0.coverage["unassigned_spans"])
    assert l1.text.count(first) == l1.text.count(second) == 1
    assert len(l1.omitted_by_record) == 1
    assert l2.record_ids == l1.record_ids == l0.record_ids == ("activity-1", "activity-2")
    for digest in (l0, l1, l2):
        assert digest.restore_normalized() == l0.text
        for title, audience, *_ in record_lines:
            assert title in digest.text and audience in digest.text
    assert l2.text.count("Built synthetic components.") == 2
    assert len(l2.omitted_by_record) == 2
    assert l2.unassigned_omitted > 0
    reduced = builder.build(2, lambda text: measure(text, 800), cap=35)
    assert reduced.unassigned_omitted > 0
    assert reduced.unassigned_carried + reduced.unassigned_omitted == l0.coverage["unassigned"]
    assert "Synthetic Example" in reduced.text
    assert "[حذف " in reduced.text and reduced.restore_normalized() == l0.text


def test_shared_cap_retention_increases_with_budget_and_preserves_short_input():
    raw, layout, structured, *_ = _document()
    builder = ResumeDigestBuilder(raw, structured, layout)
    assert Settings.model_fields["RESUME_DIGEST_DESCRIPTION_CAP"].default is None
    limits = list(range(350, 2501, 50))
    results = [builder.build(2, lambda text: PromptBudget(len(text), 0, limit, "exact")) for limit in limits]
    percentages = [result.retained_pct for result in results]
    assert percentages == sorted(percentages)
    assert results[0].unassigned_omitted > 0 and results[-1].unassigned_omitted == 0
    assert all(not result.budget.over_by for result in results)
    limit = 1150
    assert builder.build(0, lambda text: PromptBudget(len(text), 0, limit, "exact")).budget.over_by
    assert results[limits.index(limit)].budget.prompt_tokens / limit >= 0.9
    assert all(result.restore_normalized() == builder.normalized.text for result in results)
    short = "مهارت‌ها\nC++ و C#"
    digest = ResumeDigestBuilder(short, {}, None).build(2, lambda text: PromptBudget(len(text), 0, 1000, "exact"))
    assert digest.text == short and digest.edits == () and digest.retained_pct == 100


@pytest.mark.parametrize("with_layout", [False, True])
def test_duplicate_titles_use_distinct_evidence_ranges_and_keep_both_ids(with_layout):
    raw = (
        "Experience\nSoftware Engineer\nExample Systems\n01/2020 - 12/2020\n"
        "Software Engineer\nFixture Labs\n01/2023 - 12/2023"
    )
    layout = (
        {
            "pages": [
                {
                    "number": 1,
                    "blocks": [
                        {"id": str(i), "bbox": [0, i, 10, i + 1], "text": line}
                        for i, line in enumerate(raw.splitlines())
                    ],
                }
            ]
        }
        if with_layout
        else None
    )
    structured = build_structured(raw, layout, reference=date(2026, 1, 1))
    builder = ResumeDigestBuilder(raw, structured, layout)
    for level in range(3):
        digest = builder.build(level, lambda text: PromptBudget(len(text), 0, 1000, "exact"), cap=0)
        assert digest.record_ids == ("activity-1", "activity-2")
        assert digest.coverage["ambiguous_attribution"] == 0
        assert digest.text.count("Software Engineer") == 2
        assert "Example Systems\n01/2020 - 12/2020" in digest.text
        assert "Fixture Labs\n01/2023 - 12/2023" in digest.text


def test_tokenizer_content_changes_l2_cache_key_even_with_identical_file_metadata(tmp_path):
    tokenizers = pytest.importorskip("tokenizers")
    paths = [tmp_path / name for name in ("a.json", "b.json")]
    for path, char in zip(paths, ("a", "b"), strict=True):
        tokenizer = tokenizers.Tokenizer(
            tokenizers.models.BPE(vocab={"a": 0, "b": 1, "aa": 2, "bb": 3}, merges=[(char, char)])
        )
        path.write_bytes(tokenizer.to_str().encode())
    stat = paths[0].stat()
    os.utime(paths[1], ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert paths[0].stat().st_size == paths[1].stat().st_size
    assert paths[0].stat().st_mtime_ns == paths[1].stat().st_mtime_ns
    keys = [
        cache_key("digest_l2", cap=120, icon_fonts=(), context=2048, output=640, tokenizer=str(path)) for path in paths
    ]
    assert keys[0] != keys[1]


def test_offline_measurement_labels_counts_and_summary_uses_minimum_p95_sample():
    raw, layout, structured, *_ = _document()
    result = measure_sample(raw, layout, structured, "")
    assert result["raw_exact"] == 0
    assert result["exact_fit_levels"] == []
    assert len(result["levels"]) == 3
    assert all(level["exact"] == 0 for level in result["levels"])
    assert "Synthetic Example" not in json.dumps(result)
    assert _distribution(range(49))["p95"] is None
    assert _distribution(range(50))["p95"] == 46.55


def test_record_score_matches_human_dates_once_and_excludes_drafts():
    _, _, structured, *_ = _document()
    reference_rows = [
        dict(
            type="job",
            organization="example   SYSTEMS",
            title="Software Engineer",
            start="۲۰۲۱/۰۱",
            end="۲۰۲۱/۱۲",
            page=1,
        ),
        dict(
            type="job", organization="Example Systems", title="Duplicate expectation", start="۲۰۲۱", end="۲۰۲۱", page=1
        ),
        dict(type="teaching", organization="Fixture Labs", title="Independent class", start="۱۴۰۱", end="۱۴۰۲", page=2),
    ]
    reference = HumanReference.model_validate({"review_status": "human_reviewed", "records": reference_rows})
    score = score_records(structured, reference, as_of=date(2026, 1, 1))
    assert score["record_types"]["job"] == {
        "matched": 1,
        "expected": 2,
        "predicted": 2,
        "expected_without_dates": 0,
        "predicted_without_dates": 0,
        "recall": 0.5,
        "precision": 0.5,
    }
    assert score["record_types"]["teaching"]["recall"] == 0
    assert score_records(structured, reference.model_copy(update={"review_status": "draft_unreviewed"})) == {
        "scored": 0,
        "draft_excluded": 1,
    }
    schema = json.loads((Path(__file__).resolve().parents[2] / "dev/resume_record_reference.schema.json").read_bytes())
    assert set(schema["properties"]["records"]["items"]["required"]) == set(reference_rows[0])
