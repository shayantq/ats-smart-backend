"""ارزیابی قرارداد ساخت‌یافتهٔ فعلی روی PDFهای corpus ثابت؛ بدون تغییر ارزیاب قدیمی."""

import json
from pathlib import Path

from app.core.structured_resume import build_structured, PARSER_VERSION
from app.core.analysis_evidence import build_analysis
from app.core.text_extraction import extract_raw_text, UnreadableResumeFileError
from evaluation.resumes.run import load, summarize
from evaluation.resumes.contract import Record, digest
from evaluation.resumes.metrics import score


def adapt(structured, profile):
    result = []
    for activity in structured["activities"]:
        # مرجع فاز ۱ کارآموزی را زیر employment دارد؛ نوع محصول تغییر نمی‌کند.
        kind = "employment" if activity["kind"] == "internship" else activity["kind"]
        fields = {k: activity["fields"].get(k, {}).get("value") for k in ["job_title", "company", "duration"]}
        if activity["kind"] == "project":
            fields["job_title"] = activity["fields"].get("project_name", {}).get("value")
        evidence = [e["text"] for f in activity["fields"].values() for e in f.get("evidence", []) if e.get("text")]
        result.append(Record(kind=kind, fields=fields, evidence=list(dict.fromkeys(evidence))))
    identity = {k: v.get("value") for k, v in structured["identity"].items() if k == "name"}
    for contact in structured["contacts"]:
        value = contact.get("value")
        if value and contact.get("status") != "ambiguous":
            identity.setdefault("email" if "@" in value else "phone", value)
    result.append(
        Record(
            kind="identity",
            fields=identity,
            evidence=[e["text"] for v in structured["identity"].values() for e in v.get("evidence", [])],
        )
    )
    for education in structured["education"]:
        fields = education["fields"]
        result.append(
            Record(
                kind="education",
                fields={
                    "degree": fields.get("title", {}).get("value"),
                    "university": fields.get("institution", {}).get("value"),
                },
                evidence=[e["text"] for f in fields.values() for e in f.get("evidence", [])],
            )
        )
    for skill in profile["skills"]:
        if skill["basis"] == "explicit":
            result.append(Record(kind="skill", fields={"name": skill["name"]}))
    return result


def main():
    from datetime import date

    cases, _, holdout = load()
    out = Path("training/reports/phase7")
    rows = []
    for case in cases:
        source = out / "legacy-corpus/inputs" / (case.id + ".pdf")
        records = []
        error = None
        try:
            layout = extract_raw_text(source.read_bytes(), source.name, with_layout=True)
            raw = layout.pop("raw_text")
            structured = build_structured(raw, layout, reference=date(2026, 11, 15))
            records = adapt(structured, build_analysis(raw, structured, {}, layout))
        except UnreadableResumeFileError:
            error = "unreadable_resume"
        except Exception as exc:
            error = type(exc).__name__  # noqa: BLE001
        rows.append(
            dict(
                case_id=case.id,
                status=(
                    "expected_failure" if error and error == case.expected_error else "failed" if error else "succeeded"
                ),
                error_code=error,
                failure_expectation_met=error == case.expected_error,
                language=case.language,
                input_type=case.input_type,
                split="holdout" if case.id in holdout else "development",
                metrics=score(case.expected, records),
            )
        )
    report = dict(
        version="phase7-current-documents-v1",
        adapter="structured-to-legacy-v1",
        parser_version=PARSER_VERSION,
        synthetic=True,
        production_qualified=False,
        label_status="author_draft",
        corpus_sha256=digest([c.model_dump() for c in cases]),
        summary=summarize(rows),
        rows=rows,
        limitations=["small_synthetic_corpus", "no_independent_hr_review", "different_adapter_from_phase1_baseline"],
    )
    (out / "documents-current.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(report["summary"]))


if __name__ == "__main__":
    main()
