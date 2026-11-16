"""آزمون دروازهٔ ارزیابی؛ موفقیت ساختگی به معنی تأیید تولید نیست."""

import copy

from evaluation.phase7 import evaluate, CASES
from app.core.structured_resume import build_structured


def test_challenge_keeps_all_variants_and_never_claims_hr_validation():
    report = evaluate()
    assert report["cases"] == 4 * len(CASES)
    assert len(report["rows"]) == report["cases"]
    assert report["metrics"]["errors"] == 0
    assert report["metrics"]["stable_cases"] == report["cases"]
    assert not report["production_qualified"] and not report["independent_hr_review"]


def test_wrong_reference_is_reported_as_failure_instead_of_removed():
    case = copy.deepcopy(CASES[0])
    case["work"] = [("employment", "Invented Role", "Invented Employer", "1990 - 2000")]
    report = evaluate([case])
    assert report["cases"] == 4 and report["metrics"]["exact_cases"] == 0
    assert report["metrics"]["fp"] > 0 and report["metrics"]["fn"] == 4


def test_persian_action_is_not_a_separate_job_and_company_prefix_is_preserved():
    raw = "سوابق کاری\nکارشناس داده | شرکت سپهر\n۱۴۰۱ - ۱۴۰۳\nتوسعه سرویس با Python"
    activities = build_structured(raw)["activities"]
    assert len(activities) == 1
    assert activities[0]["fields"]["company"]["value"] == "شرکت سپهر"
    assert any("Python" in c["value"] for c in activities[0]["claims"])


def test_description_does_not_fill_unknown_employer():
    activities = build_structured("EXPERIENCE\nSoftware Engineer\nBuilt Python services")["activities"]
    assert len(activities) == 1 and activities[0]["fields"]["company"]["value"] is None


def test_missing_identity_does_not_attach_the_entire_document_as_evidence():
    structured = build_structured(
        "SKILLS\nPython",
        layout={"pages": [{"number": 1, "blocks": [{"id": "p1", "text": "Python", "bbox": [0, 0, 20, 20]}]}]},
    )
    assert structured["identity"]["name"]["value"] is None
    assert structured["identity"]["name"]["evidence"] == []


def test_document_adapter_keeps_project_title_without_employment_reclassification():
    from evaluation.phase7_documents import adapt
    from app.core.analysis_evidence import build_analysis

    raw = "PROJECTS\nBeacon API | Personal project\n2024 - 2025\nBuilt Python services."
    source = build_structured(raw)
    records = adapt(source, build_analysis(raw, source, {}))
    project = next(r for r in records if r.kind == "project")
    assert project.fields["job_title"] == "Beacon API"
    assert not any(r.kind == "employment" for r in records)
