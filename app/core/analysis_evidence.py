"""تحلیل مستند فاز ۴؛ پوشش شرط با صلاحیت استخدام یا احتمال موفقیت برابر نیست."""

import hashlib
import json


VERSION = "evidence-analysis-v2.1"


def job_signature(job):
    keys = ("title", "skills_required", "description", "required_seniority", "required_education", "location")
    values = {key: (job or {}).get(key) for key in keys}
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def build_analysis(text, structured, job=None, layout=None):
    from app.core.skill_evidence import extract_skills
    from app.core.requirement_evidence import requirements
    from app.core.career_evidence import career_analysis

    job = job or {}
    skills = extract_skills(text, structured, layout)
    matrix = requirements(job, skills, structured)
    career, achievements, transitions, projects = career_analysis(structured, skills)
    required = [r for r in matrix if r["priority"] == "required"]
    quality_ok = not layout or layout.get("status") != "partial"
    lower = sum(r["status"] == "met" for r in required)
    unknown = sum(r["status"] == "unknown" for r in required)
    return dict(
        version=VERSION,
        job_sha256=job_signature(job),
        skills=skills,
        requirements=matrix,
        career=career,
        achievements=achievements,
        transitions=transitions,
        projects=projects,
        coverage=dict(
            lower=round(100 * lower / len(required), 2) if required and quality_ok else None,
            upper=round(100 * (lower + unknown) / len(required), 2) if required and quality_ok else None,
            denominator=len(required),
            met=lower,
            unknown=unknown,
            unmet=sum(r["status"] == "unmet" for r in required),
            weighting="equal_required_v1",
            calibrated=False,
            suppressed_reason="partial_extraction" if not quality_ok else "no_requirements" if not required else None,
        ),
        hiring_score=None,
        calibration="requires_independent_hr_review",
        assessment_status="provisional_rule_based",
        evaluation_reference="synthetic_author_draft",
        limitations=[
            "missing_is_unknown",
            "inferred_is_not_practical_experience",
            "no_hiring_decision",
            "context_dates_are_not_skill_duration",
            "unknown_requirement_abstention",
            "source_claim_is_not_independent_verification",
        ],
    )
