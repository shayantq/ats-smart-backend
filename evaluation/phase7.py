"""ارزیابی شفاف و قابل بازتولید؛ شکست‌ها حذف و مرجع‌های قدیمی بازنویسی نمی‌شوند."""

import argparse
import copy
import hashlib
import json
import time
from collections import Counter
from datetime import date
from pathlib import Path

from app.core.analysis_evidence import build_analysis, VERSION
from app.core.structured_resume import build_structured
from evaluation.phase7_cases import CASES, OUT_OF_SCOPE
from evaluation.resumes.contract import digest
from evaluation.resumes.metrics import norm
from evaluation.resumes.run import load

REFERENCE = date(2026, 11, 16)
ROOT = Path(__file__).resolve().parents[1]


def work_records(structured):
    return [
        tuple([a["kind"]] + [a["fields"][k].get("value") for k in ["job_title", "company", "duration"]])
        for a in structured.get("activities", [])
        if a["kind"] in {"employment", "internship"}
    ]


def canonical(records):
    return Counter(tuple(str(norm(v)) if v is not None else None for v in row) for row in records)


def qualification_signature(profile, structured):
    # هویت و محل شاهد در نسخهٔ تغییرنام‌یافته عمداً جزو صلاحیت محسوب نمی‌شوند.
    return digest(
        dict(
            requirements=[(r["text"], r["status"]) for r in profile["requirements"]],
            coverage=profile["coverage"],
            work=work_records(structured),
            skills=sorted({s.get("canonical", s.get("name", "")) for s in profile["skills"]}),
        )
    )


def evaluate(cases=CASES):
    rows = []
    for case in cases:
        baseline = None
        for variant in ["original", "spacing", "name_swap", "gender_marker"]:
            name = "NORA VALE" if case["language"] != "fa" else "نورا سپهری"
            if variant == "name_swap":
                name = "OMAR VALE" if case["language"] != "fa" else "آرمان سپهری"
            raw = name + "\n" + ("Gender: Female\n" if variant == "gender_marker" else "") + case["body"]
            if variant == "spacing":
                raw = "\n\n".join("  " + line + "  " for line in raw.splitlines())
            started = time.perf_counter()
            try:
                structured = build_structured(raw, reference=REFERENCE)
                profile = build_analysis(raw, structured, {"skills_required": ["Python", "Docker"]})
                actual = canonical(work_records(structured))
                expected = canonical(case["work"])
                tp = sum((actual & expected).values())
                fp = sum((actual - expected).values())
                fn = sum((expected - actual).values())
                signature = qualification_signature(profile, structured)
                if variant == "original":
                    baseline = signature
                evidence_missing = sum(
                    1
                    for a in structured.get("activities", [])
                    for f in a.get("fields", {}).values()
                    if f.get("value") is not None and not f.get("evidence")
                )
                rows.append(
                    dict(
                        case_id=case["id"],
                        lineage=case["id"],
                        variant=variant,
                        language=case["language"],
                        source_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                        tp=tp,
                        fp=fp,
                        fn=fn,
                        records_exact=fp == 0 and fn == 0,
                        identity_correct=norm(structured["identity"]["name"].get("value")) == norm(name),
                        qualification_stable=signature == baseline,
                        evidence_missing=evidence_missing,
                        error=None,
                        ms=round((time.perf_counter() - started) * 1000, 3),
                    )
                )
            except Exception as error:  # noqa: BLE001
                rows.append(
                    dict(
                        case_id=case["id"],
                        lineage=case["id"],
                        variant=variant,
                        language=case["language"],
                        tp=0,
                        fp=0,
                        fn=len(case["work"]),
                        records_exact=False,
                        identity_correct=False,
                        qualification_stable=False,
                        evidence_missing=None,
                        error=type(error).__name__,
                    )
                )
    counts = {k: sum(r[k] for r in rows) for k in ["tp", "fp", "fn"]}
    tp, fp, fn = [counts[k] for k in ["tp", "fp", "fn"]]
    return dict(
        version="phase7-diagnostic-v1",
        analysis_version=VERSION,
        reference_date=REFERENCE.isoformat(),
        synthetic=True,
        label_status="author_draft",
        independent_hr_review=False,
        production_qualified=False,
        corpus_sha256=digest(cases),
        families=len(cases),
        cases=len(rows),
        metrics=dict(
            **counts,
            precision=tp / (tp + fp) if tp + fp else None,
            recall=tp / (tp + fn) if tp + fn else None,
            exact_cases=sum(r["records_exact"] for r in rows),
            identity_cases=sum(r["identity_correct"] for r in rows),
            stable_cases=sum(r["qualification_stable"] for r in rows),
            errors=sum(r["error"] is not None for r in rows),
        ),
        rows=rows,
        out_of_scope=OUT_OF_SCOPE,
        hr_usefulness=dict(measured=False, reason="no_independent_hr_labels"),
        fairness=dict(kind="limited_metamorphic_proxy_check", population_fairness_proven=False),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "training/reports/phase7")
    args = parser.parse_args()
    old = ROOT / "evaluation/resumes/corpus/holdout.json"
    frozen = hashlib.sha256(old.read_bytes()).hexdigest()
    load()  # اعتبار lineage و اثرانگشت مرجع قدیمی پیش از آزمون.
    report = evaluate()
    load()
    assert hashlib.sha256(old.read_bytes()).hexdigest() == frozen, "holdout_modified"
    report["legacy_holdout_unchanged"] = True
    report["legacy_holdout_file_sha256"] = frozen
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "quality.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    (args.out / "challenge-manifest.json").write_text(
        json.dumps(
            dict(
                corpus_sha256=report["corpus_sha256"],
                synthetic=True,
                label_status="author_draft",
                cases=copy.deepcopy(CASES),
            ),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf8",
    )
    print(
        json.dumps(
            {k: report[k] for k in ["families", "cases", "metrics", "legacy_holdout_unchanged", "production_qualified"]}
        )
    )


if __name__ == "__main__":
    main()
