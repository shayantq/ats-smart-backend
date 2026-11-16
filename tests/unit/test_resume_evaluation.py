"""صحت سنجه با خروجی‌های عمداً غلط سنجیده می‌شود، نه با نام کلاس CSS یا پیاده‌سازی محصول."""

import json

import pytest

from evaluation.resumes.contract import Record, validate_corpus
from evaluation.resumes.metrics import score, prf
from evaluation.resumes.run import load, CORPUS


def row(company="Synthetic Lab", title="Engineer", duration="2020 - 2022", **kw):
    return Record(kind="employment", fields=dict(company=company, job_title=title, duration=duration), **kw)


def test_perfect_and_missing_outputs_have_real_denominators():
    expected = [row(evidence=["source"])]
    assert score(expected, expected)["records"]["f1"] == 1
    missing = score(expected, [])
    assert missing["fields"]["fn"] == 3
    assert missing["records"]["recall"] == 0
    assert missing["omissions"] == 1
    assert prf(0, 0, 0)["f1"] is None


def test_fabrication_and_duplicate_are_not_rewarded():
    expected = [row()]
    predicted = [row(), row(), row(company="Invented", title="Manager", duration="99 years")]
    result = score(expected, predicted)
    assert result["duplicates"] == 1
    assert result["unsupported_records"] == 2
    assert result["records"]["precision"] == pytest.approx(1 / 3)


def test_swapped_employers_are_linkage_errors_even_when_words_are_present():
    expected = [row("A", "Engineer"), row("B", "Manager")]
    predicted = [row("B", "Engineer"), row("A", "Manager")]
    result = score(expected, predicted)
    assert result["incorrect_linkage"] == 2
    assert result["records"]["tp"] == 0


def test_wrong_section_and_dates_cannot_pass():
    expected = [row()]
    predicted = [row(duration="2020 - 2030")]
    assert score(expected, predicted)["dates"] == {"correct": 0, "denominator": 1}
    predicted[0].kind = "project"
    assert score(expected, predicted)["records"]["tp"] == 0


def test_unknown_information_requires_abstention_and_real_evidence():
    a = row(duration=None, evidence=["real source"])
    b = row(duration="ten years", evidence=["invented source"])
    result = score([a], [b])
    assert result["unknown"]["inappropriate_certainty"] == 1
    assert result["evidence"]["covered"] == 0


def test_corpus_is_frozen_and_lineages_do_not_leak():
    cases, dev, hold = load()
    frozen = json.loads((CORPUS / "holdout.json").read_text())["sha256"]
    assert validate_corpus(cases, dev, hold, frozen)
    cases[0].lineage = next(c for c in cases if c.id == hold[0]).lineage
    # تغییر محتوا یا lineage مرجع با fingerprint یا جداسازی کشف می‌شود.
    with pytest.raises(AssertionError):
        validate_corpus(cases, dev, hold, frozen)


def test_unsupported_label_and_changed_holdout_are_rejected():
    cases, dev, hold = load()
    frozen = json.loads((CORPUS / "holdout.json").read_text())["sha256"]
    cases[0].expected[0].fields["company"] = "not in source"
    with pytest.raises(AssertionError, match="label_value_not_supported"):
        validate_corpus(cases, dev, hold, frozen)
    with pytest.raises(AssertionError, match="holdout_changed"):
        validate_corpus(load()[0], dev, hold, "wrong")


def test_numeric_tolerance_is_bounded_and_false_evidence_not_accepted():
    a = Record(kind="experience_total", fields={"years": 3.001}, evidence=["whole source span"])
    b = Record(kind="experience_total", fields={"years": 3.002}, evidence=["source span"])
    assert score([a], [b])["dates"]["correct"] == 1
    b.fields["years"] = 6.0
    assert score([a], [b])["dates"]["correct"] == 0


def test_generated_pdf_is_reproducible_and_types_are_real(tmp_path):
    import fitz
    from pathlib import Path
    from evaluation.resumes.fixtures import render

    cases, _, _ = load()
    by_id = {c.id: c for c in cases}
    font = Path("frontend/public/fonts")
    a = render(by_id["en-inline"], tmp_path / "a", font)
    b = render(by_id["en-inline"], tmp_path / "b", font)
    assert a.read_bytes() == b.read_bytes()
    with fitz.open(a) as pdf:
        assert pdf[0].get_text().strip()
    with fitz.open(render(by_id["en-inline-image"], tmp_path / "c", font)) as pdf:
        assert not pdf[0].get_text().strip()
    with fitz.open(render(by_id["mixed-hybrid"], tmp_path / "d", font)) as pdf:
        assert pdf[0].get_text().strip() and not pdf[1].get_text().strip()


def test_stage_failure_keeps_false_negatives_and_redacts_exception(tmp_path, monkeypatch):
    from datetime import date
    from evaluation.resumes.run import baseline

    def fail(*args, **kwargs):
        raise ValueError("sensitive exception payload")

    monkeypatch.setattr("app.core.text_extraction.extract_raw_text", fail)
    file = tmp_path / "synthetic.pdf"
    file.write_bytes(b"synthetic")
    result = baseline(load()[0][0], file, date(2026, 11, 15), False)
    assert result["status"] == "failed"
    assert result["metrics"]["fields"]["fn"] > 0
    assert "sensitive" not in json.dumps(result)


def test_review_is_append_only_and_does_not_rewrite_frozen_labels(tmp_path, monkeypatch):
    from evaluation.resumes.review import main

    before = (CORPUS / "cases.json").read_bytes()
    ledger = tmp_path / "review.jsonl"
    monkeypatch.setattr(
        "sys.argv",
        [
            "review",
            "--case",
            "en-inline",
            "--reviewer",
            "test-only",
            "--decision",
            "approve",
            "--attest-independent-review",
            "--ledger",
            str(ledger),
        ],
    )
    main()
    main()
    assert len(ledger.read_text().splitlines()) == 2
    assert (CORPUS / "cases.json").read_bytes() == before
