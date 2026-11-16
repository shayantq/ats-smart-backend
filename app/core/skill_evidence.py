"""واژگان و شاهد مهارت؛ رابطهٔ والد از هم‌ارزی جداست و تکرار، احتمال صحت نیست."""

import re
from datetime import date

from app.core.resume_dates import normalize, endpoint
from app.core.skill_graph import SKILL_ONTOLOGY
from app.core.structured_resume import evidence, sections

ALIASES = {
    "Python": ["پایتون"],
    "JavaScript": ["جاوااسکریپت", "جاوا اسکریپت"],
    "TypeScript": ["تایپ اسکریپت"],
    "React": ["React.js", "ReactJS", "ری‌اکت"],
    "Node.js": ["NodeJS", "Node JS"],
    "PostgreSQL": ["Postgres", "پستگرس"],
    "Docker": ["داکر"],
    "Kubernetes": ["K8s", "کوبرنتیز"],
    "Git": ["گیت"],
    "C++": [],
    "HTML": ["HTML5"],
    "CSS": ["CSS3"],
    "Linux": ["لینوکس"],
    "REST": ["RESTful"],
    "GraphQL": [],
    "GitHub Actions": [],
    "Alembic": [],
    "Pydantic": [],
}
PARENTS = {child: root for root, children in SKILL_ONTOLOGY.items() for child in children}
CANONICAL = {normalize(s): s for root, children in SKILL_ONTOLOGY.items() for s in [root, *children]}
for name, variants in ALIASES.items():
    for value in [name, *variants]:
        CANONICAL[normalize(value)] = name
PATTERN = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(s) for s in sorted(CANONICAL, key=len, reverse=True)) + r")(?!\w)"
)
NEGATION = re.compile(r"\b(?:no|without|never|not(?! only))\b|بدون|فاقد|ندارم|ندارد", re.I)
ACTION = re.compile(r"\b(?:built|developed|implemented|used|maintained|deployed|created)\b|پیاده|استفاده|ساخت", re.I)
LEARNING = re.compile(r"\b(?:learning|interested|studying)\b|یادگیری|علاقه", re.I)


def mentions(text):
    value = normalize(text)
    return [(CANONICAL[m.group()], m.start(), m.end()) for m in PATTERN.finditer(value)]


def extract_skills(text, structured, layout=None):
    observations = {}

    def observe(line, context, activity=None, practical=False):
        for clause in re.split(r"[;؛]|\bbut\b|اما|ولی", line, flags=re.I):
            lowered = normalize(clause)
            lowered = re.sub(r"(?:https?://|www\.|github\.com/|linkedin\.com/)[^\s<>]+|\S+@\S+", " ", lowered)
            denied, learning = bool(NEGATION.search(lowered)), bool(LEARNING.search(lowered))
            for name, start, end in mentions(lowered):
                tail = lowered[end:]
                version = re.match(r"\s+v?(\d+(?:\.\d+){0,2})(?!\w)(?!\s*(?:years?|سال)\b)", tail)
                # مدت اعلام‌شده فقط ادعاست؛ مدت استخراج‌شده از بازهٔ شغلی نیست.
                years = re.search(r"(\d+(?:\.\d+)?)\s*(?:years?|سال)\b", lowered)
                row = dict(
                    context=context,
                    activity_id=activity.get("id") if activity else None,
                    evidence=evidence(clause, layout),
                    negated=denied,
                    usage=(
                        "learning"
                        if learning
                        else "practical_claim" if practical and ACTION.search(lowered) and not denied else "mention"
                    ),
                    versions=[version[1]] if version else [],
                    interval_context=activity.get("dates") if activity else None,
                    skill_duration_years=None,
                    claimed_years=float(years[1]) if years and len(mentions(clause)) == 1 else None,
                )
                last_used = re.search(r"last used(?: in)?\s*:?\s*(\d{4})|آخرین استفاده\s*:?\s*(\d{4})", lowered)
                if last_used and len(mentions(lowered)) == 1 and not denied:
                    try:
                        source_year = last_used[1] or last_used[2]
                        earliest, latest, precision, _ = endpoint(
                            source_year, date.fromisoformat(structured["reference_date"])
                        )
                        if earliest <= date.fromisoformat(structured["reference_date"]):
                            row["last_used_claim"] = dict(
                                value=source_year,
                                precision=precision,
                                earliest=earliest.isoformat(),
                                latest=latest.isoformat(),
                                evidence=row["evidence"],
                                status="attributed",
                            )
                    except ValueError:
                        pass
                observations.setdefault(name, []).append(row)
                parent = PARENTS.get(name)
                if parent and parent != name:
                    observations.setdefault(parent, []).append(dict(row, inferred_from=name, usage="inferred"))

    for label, lines in sections(text).items():
        if label in {"skills", "summary", "certifications", "education"}:
            for line in lines:
                observe(line, label)
    for activity in structured.get("activities", []):
        fields = activity["fields"]
        title = fields.get("job_title") or fields.get("project_name") or {}
        if title.get("value"):
            observe(title["value"], activity["kind"], activity)
        for claim in activity.get("claims", []):
            if claim.get("value"):
                observe(claim["value"], activity["kind"], activity, practical=True)
    output = []
    for name, refs in sorted(observations.items()):
        positive = [r for r in refs if not r["negated"] and not r.get("inferred_from") and r["usage"] != "learning"]
        negative = [r for r in refs if r["negated"] and not r.get("inferred_from")]
        output.append(
            dict(
                name=name,
                basis=(
                    "explicit"
                    if positive
                    else (
                        "negated"
                        if negative
                        else "learning" if all(r["usage"] == "learning" for r in refs) else "inferred"
                    )
                ),
                conflict=bool(positive and negative),
                observations=refs,
                confidence=None,
                duration_years=None,
                last_used=[
                    r["last_used_claim"] for r in refs if r.get("last_used_claim") and not r.get("inferred_from")
                ]
                or None,
            )
        )
    return output
