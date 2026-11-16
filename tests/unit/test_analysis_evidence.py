"""تست تحلیل مستند با ورودی‌های ساختگی و شروط منفی و مبهم."""

from datetime import date

from app.core.analysis_evidence import build_analysis
from app.core.structured_resume import build_structured


def analyze(text, job=None, layout=None):
    return build_analysis(text, build_structured(text, reference=date(2026, 11, 16)), job, layout)


def test_explicit_inferred_practical_and_credential_are_distinct():
    text = (
        "SKILLS\nFastAPI\nCERTIFICATIONS\nAWS Certification\nEXPERIENCE\n"
        "Engineer | Maple Labs\n2020 - 2024\nBuilt a service using FastAPI."
    )
    result = analyze(text)
    skills = {x["name"]: x for x in result["skills"]}
    assert skills["Python"]["basis"] == "inferred"
    assert skills["FastAPI"]["basis"] == "explicit"
    assert any(x["usage"] == "practical_claim" for x in skills["FastAPI"]["observations"])
    assert all(x["usage"] != "practical_claim" for x in skills["AWS"]["observations"])
    assert skills["FastAPI"]["duration_years"] is None


def test_missing_skill_is_unknown_and_parent_inference_does_not_satisfy_requirement():
    r = analyze("SKILLS\nFastAPI", {"skills_required": ["Python", "Java", "FastAPI"]})
    assert [x["status"] for x in r["requirements"]] == ["unknown", "unknown", "met"]
    assert r["coverage"]["denominator"] == 3
    assert r["coverage"]["upper"] == 100
    assert r["hiring_score"] is None


def test_explicit_denial_conflict_and_ambiguous_condition():
    r = analyze("SKILLS\nNo Java experience\nPython", {"skills_required": ["Java", "Python or Java"]})
    assert [x["status"] for x in r["requirements"]] == ["unmet", "met"]
    r = analyze("SKILLS\nPython\nNo Python experience", {"skills_required": ["Python"]})
    assert r["requirements"][0]["status"] == "unknown"


def test_partial_extraction_suppresses_coverage_and_identity_is_ignored():
    r = analyze("JANE JAVA\nSKILLS\nPython", {"skills_required": ["Python"]}, {"status": "partial"})
    assert r["coverage"]["lower"] is None
    assert "Java" not in [s["name"] for s in r["skills"]]


def test_fairness_and_determinism_do_not_use_name_location_or_gaps():
    job = {"skills_required": ["Python"]}
    a = analyze("JANE DOE\nHarbor City, Iran\nSKILLS\nPython", job)
    b = analyze("JOHN ROE\nDifferent City, Canada\nSKILLS\nPython", job)
    assert a == b


def test_no_seniority_guess_from_years_and_numerical_claim_is_attributed():
    r = analyze("EXPERIENCE\nSenior Engineer | Maple Labs\n2020 - 2024\nDeveloped a service with 30% faster response.")
    assert r["career"][0]["declared_level"] == "Senior"
    assert r["career"][0]["inferred_level"] is None
    assert r["achievements"][0]["numerical_claims"] == ["30%"]
    assert r["achievements"][0]["individual_contribution"] == "unknown"


def test_certificate_does_not_prove_experience_and_structured_conditions_are_not_ignored():
    r = analyze(
        "CERTIFICATIONS\nPython Certification",
        {"skills_required": ["Python experience"], "required_seniority": "Senior"},
    )
    assert len(r["requirements"]) == 2
    assert all(x["status"] == "unknown" for x in r["requirements"])
