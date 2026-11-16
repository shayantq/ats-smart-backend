"""مرجع‌های ساختگی مستقل از کلاس‌های CSS و با انتظار صریح رفتار محصول."""

from datetime import date

import pytest

from app.core.analysis_evidence import build_analysis
from app.core.structured_resume import build_structured


def run(text, required, **kwargs):
    structured = build_structured(text, reference=date(2026, 11, 16))
    return build_analysis(text, structured, {"skills_required": required, **kwargs})


@pytest.mark.parametrize(
    "condition,status",
    [
        ("Python and Java", "unmet"),
        ("Python or Java", "met"),
        ("Python and Docker", "unknown"),
        ("Java or Docker", "unknown"),
        ("(Python or Java) and Docker", "unknown"),
        ("Python or (Java and Docker)", "met"),
        ("Python و Java", "unmet"),
        ("Python یا Java", "met"),
        ("Python and (Java", "unknown"),
        ("Python unless Java", "unknown"),
    ],
)
def test_three_state_logic_parentheses_and_unsupported_qualifiers(condition, status):
    r = run("SKILLS\nPython but no Java", [condition])
    assert r["requirements"][0]["status"] == status


def test_aliases_negation_scope_learning_and_false_substrings():
    r = run(
        "SKILLS\nPostgres; ReactJS; Kubernetes; JavaScript\nPython but no Java\nLearning Docker",
        ["PostgreSQL", "React", "K8s", "Java", "Docker"],
    )
    assert [x["status"] for x in r["requirements"]] == ["met", "met", "met", "unmet", "unknown"]
    assert next(s for s in r["skills"] if s["name"] == "Python")["basis"] == "explicit"
    r = run("SKILLS\nJavaScript", ["Java"])
    assert r["requirements"][0]["status"] == "unknown"


def test_versions_numeric_comparison_and_years_are_not_versions():
    r = run("SKILLS\nPython 3.11", ["Python >= 3.9", "Python >= 3.12", "Python 3"])
    assert [x["status"] for x in r["requirements"]] == ["met", "unknown", "met"]
    r = run("SKILLS\nPython 3 years", ["Python >= 3.1"])
    assert r["requirements"][0]["status"] == "unknown"


def test_duration_claim_not_whole_job_and_conflicting_job_contract_abstains():
    r = run("EXPERIENCE\nEngineer | Maple Labs\n2020 - 2024\nBuilt APIs using Python.", ["3 years Python experience"])
    assert r["requirements"][0]["status"] == "unknown"
    r = run("SKILLS\nPython", ["Python"], description="Python not required")
    assert all(x["status"] == "unknown" for x in r["requirements"])


def test_role_transition_leadership_domain_and_non_percentage_claim():
    r = run(
        "EXPERIENCE\nBackend Engineer | Maple Labs\n2020/01/01 - 2022/01/01\n"
        "Built APIs serving 10000 users.\nFrontend Engineer | Maple Labs\n2023/01/01 - 2024/01/01\n"
        "Led a team and mentored colleagues.\nIndustry: healthcare",
        [],
    )
    assert {t["kind"] for t in r["transitions"]} == {"same_employer_role_change", "role_family_change"}
    assert all(not t.get("promotion_verified") for t in r["transitions"])
    assert r["achievements"][0]["numerical_claims"] == ["10000 users"]
    assert r["career"][1]["industry"][0]["value"] == "healthcare"
    assert len(r["career"][1]["leadership_signals"]) == 2
    assert r["career"][1]["inferred_level"] is None


def test_skill_context_does_not_invent_last_used_or_duration():
    r = run("EXPERIENCE\nEngineer | Maple Labs\n2020 - 2024\nBuilt Python services.", [])
    assert r["skills"][0]["last_used"] is None
    assert r["skills"][0]["duration_years"] is None


def test_last_used_is_an_explicit_claim_and_url_substring_is_not_a_skill():
    r = run("SKILLS\nPython last used in 2024\nhttps://example.invalid/Java", [])
    assert len(r["skills"]) == 1
    assert r["skills"][0]["last_used"][0]["value"] == "2024"
    assert r["skills"][0]["last_used"][0]["status"] == "attributed"
    r = run("SKILLS\nPython last used in 2030", [])
    assert r["skills"][0]["last_used"] is None


def test_repeated_job_requirement_does_not_inflate_denominator():
    r = run("SKILLS\nPython", ["Python"], description="Python required")
    assert r["coverage"]["denominator"] == 1
    assert len(r["requirements"][0]["sources"]) == 2


def test_degree_condition_uses_declared_degree_not_skill_keyword():
    r = run("EDUCATION\nBachelor of Computer Science\nExample University", [], required_education="Bachelor")
    assert r["requirements"][0]["status"] == "met"
    r = run("SKILLS\nPython", [], required_education="Bachelor")
    assert r["requirements"][0]["status"] == "unknown"
