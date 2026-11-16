"""تشخیص خط مبنا با دستور python -m evaluation.resumes.run؛ بدون نوشتن در دیتابیس."""

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import logging
import platform
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from evaluation.resumes.contract import Case, Record, digest, validate_corpus
from evaluation.resumes.fixtures import render
from evaluation.resumes.metrics import score, prf

CORPUS = Path(__file__).parent / "corpus"


def load():
    cases = [Case.model_validate(x) for x in json.loads((CORPUS / "cases.json").read_text(encoding="utf8"))]
    dev = json.loads((CORPUS / "development.json").read_text())
    hold = json.loads((CORPUS / "holdout.json").read_text())
    validate_corpus(cases, dev, hold["ids"], hold["sha256"])
    return cases, dev, hold["ids"]


def adapt(raw, parsed, reference):
    from app.core.employment_evidence import extract_employment, analyze_evidence
    from app.core.skill_graph import match_skills

    entries, years = analyze_evidence(extract_employment(raw), reference)
    records = [
        Record(
            kind="employment",
            fields={k: x.get(k) for k in ("company", "job_title", "duration")},
            evidence=[x["evidence"]] if x.get("evidence") else [],
        )
        for x in entries
    ]
    records += [Record(kind="skill", fields={"name": s}) for s in match_skills(raw)]
    records += [Record(kind="identity", fields=parsed["personal_info"])]
    records += [
        Record(kind="education", fields={k: v for k, v in x.items() if k in {"degree", "university"}})
        for x in parsed["education"]
    ]
    return records, years


def baseline(case, path, reference, model):
    from app.core.text_extraction import extract_raw_text, UnreadableResumeFileError
    from app.core.resume_parser import parse_resume_text
    from app.model_inference.client import InferenceError

    started = time.perf_counter()
    timings, output, error = {}, [], None
    stage = "extraction"
    years = None
    try:
        tick = time.perf_counter()
        raw = extract_raw_text(path.read_bytes(), filename="synthetic.pdf")
        timings["extraction_ms"] = (time.perf_counter() - tick) * 1000
        stage, tick = "parsing", time.perf_counter()
        parsed = parse_resume_text(raw).model_dump()
        timings["parsing_ms"] = (time.perf_counter() - tick) * 1000
        output, years = adapt(raw, parsed, reference)
        if model:
            from app.core.config import settings
            from app.model_inference.pipeline import run_model_pipeline

            host = urlparse(settings.MODEL_INFERENCE_URL).hostname
            if host not in {"localhost", "127.0.0.1", "host.docker.internal"}:
                raise ValueError("local_endpoint_required")
            stage = "model"
            result = asyncio.run(
                run_model_pipeline(
                    path.read_bytes(),
                    "synthetic.pdf",
                    {"title": "Software Engineer", "skills_required": ["Python"]},
                    saved_text=raw,
                    saved_parsed=parsed,
                )
            )
            timings.update(result.metrics or {})
            # خروجی واقعی نگاشت‌شدهٔ محصول؛ هیچ پاسخ ساختگی به مدل داده نمی‌شود.
            output = [x for x in output if x.kind != "employment"]
            output += [
                Record(
                    kind="employment",
                    fields={k: getattr(x, k) for k in ("company", "job_title", "duration")},
                    evidence=[x.evidence] if x.evidence else [],
                )
                for x in result.analysis.experience.entries
            ]
            years = result.analysis.experience.total_experience_years
    except UnreadableResumeFileError:
        error = "unreadable_resume"
    except InferenceError as exc:
        error = exc.code
    except Exception:
        error = "stage_error"
    timings["total_ms"] = (time.perf_counter() - started) * 1000
    metrics = score(case.expected, output)
    metrics["duration_union"] = dict(
        denominator=int(case.duration_range_years is not None),
        correct=int(
            case.duration_range_years is not None
            and years is not None
            and case.duration_range_years[0] <= years <= case.duration_range_years[1]
        ),
        status="measured" if case.duration_range_years else "not_labeled",
    )
    return dict(
        case_id=case.id,
        language=case.language,
        layout=case.layout,
        input_type=case.input_type,
        input_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        metrics=metrics,
        status="expected_failure" if error and error == case.expected_error else "failed" if error else "completed",
        failure_stage=stage if error else None,
        error_code=error,
        timings_ms=timings,
        failure_expectation_met=(error == case.expected_error),
        sections={"status": "not_measured", "reason": "product_does_not_expose_section_labels"},
    )


def summarize(rows):
    totals = {k: sum(r["metrics"]["fields"][k] for r in rows) for k in ("tp", "fp", "fn")}
    f1 = [r["metrics"]["fields"]["f1"] for r in rows if r["metrics"]["fields"]["f1"] is not None]
    return dict(
        cases=len(rows),
        fields_micro=prf(**totals),
        fields_macro_f1=sum(f1) / len(f1) if f1 else None,
        macro_denominator=len(f1),
        macro_excluded_empty=len(rows) - len(f1),
        stage_failures=sum(r["status"] == "failed" for r in rows),
        omissions=sum(r["metrics"]["omissions"] for r in rows),
        unsupported_records=sum(r["metrics"]["unsupported_records"] for r in rows),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("training/reports/resume-eval-v1"))
    parser.add_argument("--font-dir", type=Path, default=Path("frontend/public/fonts"))
    parser.add_argument("--split", choices=["development", "holdout", "all"], default="development")
    parser.add_argument("--model", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()
    if args.model and (args.limit is None or not 1 <= args.limit <= 2 or args.split != "development"):
        parser.error("model smoke requires development split and limit 1..2")
    if args.limit is not None and args.limit < 1:
        parser.error("limit must be positive")
    cases, dev, hold = load()
    ids = dev if args.split == "development" else hold if args.split == "holdout" else dev + hold
    selected = [next(c for c in cases if c.id == i) for i in ids][: args.limit]
    args.out.mkdir(parents=True, exist_ok=True)
    # جلوگیری از ورود پیام‌های کتابخانه‌ها یا متن خطای حاوی داده به stdout.
    logging.disable(logging.CRITICAL)
    reference = date(2026, 11, 15)
    rows = [baseline(c, render(c, args.out / "inputs", args.font_dir), reference, args.model) for c in selected]
    groups = {}
    for axis in ("language", "layout", "input_type"):
        bucket = defaultdict(list)
        for row in rows:
            bucket[row[axis]].append(row)
        groups[axis] = {k: summarize(v) for k, v in bucket.items()}
    import app.core.resume_parser as product

    app_root = Path(product.__file__).resolve().parents[1]
    hashes = {
        str(p.relative_to(app_root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(app_root.rglob("*.py"))
    }
    report = dict(
        version="resume-eval-v1",
        corpus_sha256=digest([c.model_dump() for c in cases]),
        source_hashes=hashes,
        evaluator_sha256=digest(
            {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob("*.py")}
        ),
        matching="normalized_exact_greedy_one_to_one_v1",
        reference_date=reference.isoformat(),
        label_review="author_draft_not_human_reviewed",
        mode="real_local_model" if args.model else "parser_only_no_model",
        model_reference_date="system_clock" if args.model else None,
        split=args.split,
        selected=len(rows),
        corpus_cases=len(cases),
        versions={n: importlib.metadata.version(n) for n in ("PyMuPDF", "pydantic", "jdatetime", "pytesseract")},
        python=platform.python_version(),
        summary=summarize(rows),
        groups=groups,
        cases=rows,
        limitations=[
            "small_synthetic_corpus",
            "sections_not_exposed",
            "labels_not_independently_reviewed",
            "no_score_calibration",
            "no_quality_claim_for_real_applicants",
        ],
    )
    if args.compare:
        before = json.loads(args.compare.read_text())
        for k in ("version", "corpus_sha256", "evaluator_sha256", "matching", "reference_date", "mode", "split"):
            if before[k] != report[k]:
                raise ValueError("incomparable_baselines")
        if [r["case_id"] for r in before["cases"]] != [r["case_id"] for r in rows]:
            raise ValueError("incomparable_case_sets")
        report["comparison"] = {
            k: report["summary"]["fields_micro"][k] - before["summary"]["fields_micro"][k] for k in ("tp", "fp", "fn")
        }
    (args.out / "baseline.json").write_text(json.dumps(report, indent=2), encoding="utf8")
    summary = report["summary"]
    lines = [
        "# گزارش خط مبنای ساختگی",
        "",
        "این نتیجه معیار کیفیت رزومه‌های واقعی نیست.",
        f"حالت: {report['mode']}؛ تعداد: {len(rows)}؛ برچسب‌ها: author_draft",
        "",
        f"Precision: {summary['fields_micro']['precision']}؛ "
        f"Recall: {summary['fields_micro']['recall']}؛ F1: {summary['fields_micro']['f1']}",
        "",
        "| شناسه | وضعیت | TP | FP | FN |",
        "|---|---|---:|---:|---:|",
    ]
    for row in rows:
        m = row["metrics"]["fields"]
        lines.append(f"| {row['case_id']} | {row['status']} | {m['tp']} | {m['fp']} | {m['fn']} |")
    (args.out / "report.md").write_text("\n".join(lines), encoding="utf8")
    print(json.dumps(report["summary"]))


if __name__ == "__main__":
    main()
