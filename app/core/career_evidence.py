"""مسیر و دستاورد با شاهد؛ تغییر سمت لزوماً ارتقا و نتیجهٔ تیم لزوماً سهم فرد نیست."""

import re

from app.core.resume_dates import normalize

LEVEL = re.compile(r"\b(junior|senior|lead|manager|intern)\b|کارآموز|ارشد|مدیر", re.I)
FAMILIES = {
    "backend": r"backend|back.end|بک.?اند",
    "frontend": r"frontend|front.end|فرانت",
    "data": r"data (?:engineer|scientist|analyst)|مهندس داده|تحلیل.?گر داده",
    "operations": r"devops|site reliability|عملیات",
}
SIGNALS = {
    "people_management": r"managed (?:a )?team|line management|مدیریت تیم",
    "technical_leadership": r"led (?:a )?team|technical lead|رهبری تیم|راهبری فنی",
    "mentoring": r"mentor(?:ed|ing)?|آموزش همکار|منتور",
    "promotion_claim": r"promot(?:ed|ion)|ارتقا",
}
NUMBERS = re.compile(
    r"\d+(?:[.,]\d+)*\s*(?:%|درصد|ms\b|milliseconds?\b|seconds?\b|users?\b|requests?\b|"
    r"million\b|thousand\b|میلیون|هزار|کاربر|درخواست|ثانیه)",
    re.I,
)


def career_analysis(structured, skills):
    career, achievements, transitions, projects = [], [], [], []
    records = structured.get("activities", [])
    for record in records:
        fields = record["fields"]
        title = fields.get("job_title") or fields.get("project_name") or {}
        title_text = title.get("value") or ""
        declared = LEVEL.search(title_text)
        signals, domains, contributions = [], [], []
        for claim in record.get("claims", []):
            value = claim.get("value") or ""
            for kind, pattern in SIGNALS.items():
                if re.search(pattern, value, re.I):
                    signals.append(dict(kind=kind, claim=claim))
            domain = re.search(r"(?:industry|domain|حوزه|صنعت)\s*:\s*([^.;\n]+)", value, re.I)
            if domain:
                domains.append(dict(value=domain[1].strip(), evidence=claim["evidence"], status="attributed"))
            numbers = NUMBERS.findall(normalize(value))
            if numbers:
                individual = bool(re.search(r"\bI\b|من\s", value))
                team = bool(re.search(r"\b(?:team|we)\b|تیم|ما\s", value, re.I))
                achievements.append(
                    dict(
                        activity_id=record["id"],
                        claim=claim,
                        numerical_claims=numbers,
                        attribution="resume_claim",
                        individual_contribution=(
                            "individual_claim" if individual and not team else "team_claim" if team else "unknown"
                        ),
                    )
                )
            contributions.append(claim)
        technologies = [
            s["name"]
            for s in skills
            if any(
                r.get("activity_id") == record["id"] and not r.get("inferred_from") and not r["negated"]
                for r in s["observations"]
            )
        ]
        career.append(
            dict(
                activity_id=record["id"],
                title=title,
                company=fields.get("company", {}),
                declared_level=declared.group() if declared else None,
                inferred_level=None,
                industry=domains or None,
                evidence=title.get("evidence", []),
                family=[name for name, pattern in FAMILIES.items() if re.search(pattern, title_text, re.I)],
                leadership_signals=signals,
                technologies=technologies,
            )
        )
        if record["kind"] == "project":
            links = list(
                dict.fromkeys(
                    re.findall(
                        r"(?:https?://|github\.com/)[^\s<>]+", " ".join(c.get("value") or "" for c in contributions)
                    )
                )
            )
            projects.append(
                dict(
                    activity_id=record["id"],
                    title=title,
                    technologies=technologies,
                    contributions=contributions,
                    links=links,
                    links_verified=False,
                    individual_contribution="unknown",
                    duplicate_of=None,
                )
            )

    # ترتیب تنها از کران قطعی شروع گرفته می‌شود؛ بازه‌های مبهم به رابطهٔ قطعی تبدیل نمی‌شوند.
    valid = [
        r for r in records if r["kind"] in {"employment", "internship", "freelance"} and r["dates"]["status"] == "valid"
    ]
    for later in valid:
        predecessors = [r for r in valid if r["dates"]["start"]["latest"] < later["dates"]["start"]["earliest"]]
        if not predecessors:
            continue
        before = max(predecessors, key=lambda r: r["dates"]["start"]["earliest"])
        a, b = before["fields"], later["fields"]
        company_a, company_b = a.get("company", {}), b.get("company", {})
        same = bool(
            company_a.get("value")
            and company_b.get("value")
            and normalize(company_a["value"]) == normalize(company_b["value"])
        )
        role_change = normalize(a.get("job_title", {}).get("value") or "") != normalize(
            b.get("job_title", {}).get("value") or ""
        )
        if same and role_change:
            transitions.append(
                dict(
                    before=before["id"],
                    after=later["id"],
                    kind="same_employer_role_change",
                    promotion_verified=False,
                    evidence=company_a.get("evidence", []) + company_b.get("evidence", []),
                )
            )
        family_a = next(c["family"] for c in career if c["activity_id"] == before["id"])
        family_b = next(c["family"] for c in career if c["activity_id"] == later["id"])
        if family_a and family_b and set(family_a).isdisjoint(family_b):
            transitions.append(
                dict(
                    before=before["id"],
                    after=later["id"],
                    kind="role_family_change",
                    interpretation="title_based_requires_review",
                    evidence=a["job_title"]["evidence"] + b["job_title"]["evidence"],
                )
            )
    seen = {}
    for project in projects:
        key = tuple(project["links"]) or (
            normalize(project["title"].get("value") or ""),
            tuple(project["technologies"]),
        )
        if key in seen:
            project["duplicate_of"] = seen[key]
        else:
            seen[key] = project["activity_id"]
    return career, achievements, transitions, projects
