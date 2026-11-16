"""ارزیابی ساختگی فاز ۴ و دروازهٔ بازبینی مستقل؛ بدون تغییر corpus ثابت فاز ۱."""

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

from app.core.analysis_evidence import VERSION, build_analysis
from app.core.structured_resume import build_structured

CASES = [
    ("and_negative", "Python but no Java", "Python and Java", "unmet"),
    ("or_positive", "Python but no Java", "Python or Java", "met"),
    ("unknown_is_not_negative", "Python", "Java", "unknown"),
    ("and_unknown", "Python", "Python and Docker", "unknown"),
    ("nested_or", "Python", "Python or (Java and Docker)", "met"),
    ("nested_and", "Python", "(Python or Java) and Docker", "unknown"),
    ("alias_postgres", "Postgres", "PostgreSQL", "met"),
    ("alias_react", "ReactJS", "React", "met"),
    ("inference_not_equivalence", "FastAPI", "Python", "unknown"),
    ("version_numeric", "Python 3.11", "Python >= 3.9", "met"),
    ("version_insufficient", "Python 3", "Python >= 3.10", "unknown"),
    ("ambiguous_unless", "Python", "Python unless Java", "unknown"),
    ("learning_not_mastery", "Learning Docker", "Docker", "unknown"),
    ("substring_java", "JavaScript", "Java", "unknown"),
    ("persian_or", "Python", "Python یا Java", "met"),
    ("conflicting_evidence", "Python\nNo Python experience", "Python", "unknown"),
    ("negative_only", "No Python experience", "Python", "unmet"),
    ("both_negative_or", "No Python; no Java", "Python or Java", "unmet"),
    ("nested_second_branch", "Docker", "(Python and Java) or Docker", "met"),
    ("persian_alias", "پایتون", "Python", "met"),
    ("kubernetes_alias", "K8s", "Kubernetes", "met"),
    ("parent_not_mastery", "ReactJS", "JavaScript", "unknown"),
    ("cplusplus", "C++", "C++", "met"),
    ("distinct_c_languages", "C++", "C#", "unknown"),
    ("html_alias", "HTML5", "HTML", "met"),
    ("old_minor_version", "Python 3.9", "Python >= 3.10", "unknown"),
    ("new_minor_version", "Python 3.10", "Python >= 3.9", "met"),
    ("years_not_version", "Python 3 years", "Python >= 3.1", "unknown"),
    ("empty_skills", "", "Python", "unknown"),
    ("missing_parenthesis", "Python", "Python and (Java", "unknown"),
    ("optional_abstention", "Python", "Python not required", "unknown"),
    ("persian_and_unknown", "Python", "Python و Docker", "unknown"),
]


def fingerprint(case):
    return hashlib.sha256(json.dumps(case, ensure_ascii=False).encode()).hexdigest()


def review_metrics(predictions, reviews):
    accepted, seen, conflicts = {}, set(), set()
    for review in reviews:
        key = (review.get("case_id"), review.get("reviewer"))
        case = next((c for c in CASES if c[0] == key[0]), None)
        if (
            not case
            or not key[1]
            or key in seen
            or review.get("independent") is not True
            or review.get("evidence_checked") is not True
            or review.get("case_sha256") != fingerprint(case)
            or review.get("label") not in {"met", "unmet", "unknown"}
        ):
            raise ValueError("invalid_or_duplicate_review")
        seen.add(key)
        accepted.setdefault(key[0], []).append(review["label"])
    qualified = {}
    for case_id, labels in accepted.items():
        if len(set(labels)) > 1:
            conflicts.add(case_id)
        elif len(labels) >= 2:
            qualified[case_id] = labels[0]
    correct = sum(predictions[case_id] == label for case_id, label in qualified.items())
    return dict(
        reviewed_denominator=len(qualified),
        correct=correct,
        accuracy=correct / len(qualified) if qualified else None,
        disagreement_cases=len(conflicts),
        unqualified_cases=len(CASES) - len(qualified),
        calibrated=False,
        reason="synthetic_rule_quality_is_not_hiring_score_calibration",
    )


def run(out, reviews=None):
    out.mkdir(parents=True, exist_ok=True)
    rows, template = [], []
    for case in CASES:
        case_id, skills, condition, expected = case
        text = "SKILLS\n" + skills
        structured = build_structured(text, reference=date(2026, 11, 16))
        result = build_analysis(text, structured, {"skills_required": [condition]})
        predicted = result["requirements"][0]["status"]
        rows.append(dict(case_id=case_id, case_sha256=fingerprint(case), expected=expected, predicted=predicted))
        template.append(
            dict(
                case_id=case_id,
                case_sha256=fingerprint(case),
                label=None,
                reviewer=None,
                independent=False,
                evidence_checked=False,
            )
        )
    report = dict(
        version=VERSION,
        label_status="author_draft_not_independently_reviewed",
        synthetic=True,
        cases=len(rows),
        correct=sum(r["expected"] == r["predicted"] for r in rows),
        rows=rows,
        independent_review=review_metrics({r["case_id"]: r["predicted"] for r in rows}, reviews or []),
    )
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf8")
    (out / "review-template.json").write_text(json.dumps(template, indent=2), encoding="utf8")
    print(json.dumps({k: report[k] for k in ["version", "cases", "correct", "independent_review"]}))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("training/reports/phase4-v2"))
    parser.add_argument("--reviews", type=Path)
    args = parser.parse_args()
    run(args.out, json.loads(args.reviews.read_text(encoding="utf8")) if args.reviews else None)
