"""شروط محدود و قابل توضیح با منطق سه‌حالتی؛ عبارت ناشناخته حدس زده نمی‌شود."""

import re
import json

from app.core.resume_dates import normalize
from app.core.skill_evidence import PATTERN, mentions

STATES = {"met", "unmet", "unknown"}


def combine(operator, values):
    if operator == "and":
        return "unmet" if "unmet" in values else "met" if all(v == "met" for v in values) else "unknown"
    return "met" if "met" in values else "unmet" if all(v == "unmet" for v in values) else "unknown"


def expression(text):
    value = normalize(text)
    found = mentions(text)
    if not found or len(value) > 2000 or len(found) > 32:
        raise ValueError("unsupported_requirement")
    if re.search(r"not required|optional|ضروری نیست|الزامی نیست|نباید", value):
        raise ValueError("negative_requirement")
    names = [x[0] for x in found]
    index = iter(range(len(names)))
    value = PATTERN.sub(lambda _: f" S{next(index)} ", value)
    years = re.findall(r"(?:at least|minimum|حداقل)?\s*(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|سال)", value)
    if len(set(years)) > 1:
        raise ValueError("ambiguous_duration")
    value = re.sub(r"(?:at least|minimum|حداقل)?\s*\d+(?:\.\d+)?\s*\+?\s*(?:years?|سال)", " ", value)
    versions = {}

    def version_token(match):
        versions[match[1]] = dict(operator=match[2] or "prefix", value=match[3])
        return match[1]

    value = re.sub(r"(S\d+)\s+(>=|==|=)?\s*v?(\d+(?:\.\d+){0,2})(?!\w)", version_token, value)
    value = re.sub(r"\band\b|(?<!\w)و(?!\w)|&", " AND ", value)
    value = re.sub(r"\bor\b|(?<!\w)یا(?!\w)", " OR ", value)
    # فقط واژه‌های قراردادی بی‌اثر حذف می‌شوند؛ قید دلخواه و نسخهٔ عددی باقی می‌مانند و رد می‌شوند.
    filler = r"\b(?:must|required|preferred|have|with|in|of|knowledge|experience|skills?|proficiency|using|and/or)\b"
    value = re.sub(filler, " ", value, flags=re.I)
    value = re.sub(r"ضروری|الزامی|ترجیحی|تسلط|آشنایی|تجربه|سابقه|مهارت|داشتن|با|به", " ", value)
    value = value.strip(" :،,.؛ ")
    tokens = re.findall(r"S\d+|AND|OR|[()]", value)
    if re.sub(r"S\d+|AND|OR|[()\s]", "", value) or len(tokens) > 96:
        raise ValueError("unsupported_requirement")
    position = 0

    def parse(operator, child, depth):
        nonlocal position
        parts = [child(depth + 1)]
        while position < len(tokens) and tokens[position] == operator.upper():
            position += 1
            parts.append(child(depth + 1))
        return parts[0] if len(parts) == 1 else dict(operator=operator, children=parts)

    def atom(depth):
        nonlocal position
        if depth > 16 or position >= len(tokens):
            raise ValueError("invalid_expression")
        token = tokens[position]
        position += 1
        if token == "(":
            tree = parse_or(depth + 1)
            if position >= len(tokens) or tokens[position] != ")":
                raise ValueError("invalid_expression")
            position += 1
            return tree
        if not token.startswith("S"):
            raise ValueError("invalid_expression")
        return dict(skill=names[int(token[1:])], version=versions.get(token))

    def parse_and(depth):
        return parse("and", atom, depth)

    def parse_or(depth):
        return parse("or", parse_and, depth)

    tree = parse_or(0)
    if position != len(tokens):
        raise ValueError("invalid_expression")
    return tree, float(years[0]) if years else None


def evaluate(tree, skills, practical=False, years=None):
    if "operator" in tree:
        children = [evaluate(x, skills, practical, years) for x in tree["children"]]
        return dict(tree, children=children, status=combine(tree["operator"], [x["status"] for x in children]))
    skill = next((s for s in skills if s["name"] == tree["skill"]), None)
    refs = skill["observations"] if skill else []
    status = "unknown"
    if skill and not skill["conflict"]:
        if skill["basis"] == "negated":
            status = "unmet"
        elif skill["basis"] == "explicit":
            positive = [r for r in refs if not r.get("inferred_from") and not r["negated"]]
            if practical:
                positive = [r for r in positive if r["usage"] == "practical_claim"]
            if positive:
                status = "met"
            if years is not None:
                claims = [r.get("claimed_years") for r in positive if r.get("claimed_years") is not None]
                # خوداظهاری مدت در شاهد ثبت است؛ سکوت یا بازهٔ شغل به مدت مهارت تبدیل نمی‌شود.
                status = "met" if claims and min(claims) >= years else "unknown"
            if tree.get("version"):
                needed = tuple(map(int, tree["version"]["value"].split(".")))
                available = [tuple(map(int, v.split("."))) for r in positive for v in r.get("versions", [])]
                matches = [
                    v
                    for v in available
                    if len(v) >= len(needed)
                    and (v >= needed if tree["version"]["operator"] == ">=" else v[: len(needed)] == needed)
                ]
                if not matches:
                    status = "unknown"
    return dict(
        tree,
        status=status,
        evidence=[e for r in refs for e in r["evidence"]],
        reason=(
            "explicit_negative_claim"
            if status == "unmet"
            else "source_claim" if status == "met" else "insufficient_or_conflicting_evidence"
        ),
    )


def requirements(job, skills, structured):
    rows = [
        dict(text=s, priority="required", source="skills_required") for s in job.get("skills_required", []) if s.strip()
    ]
    for line in (job.get("description") or "").splitlines():
        if re.search(r"preferred|nice.to.have|ترجیحی|مزیت", line, re.I):
            rows.append(dict(text=line, priority="preferred", source="description"))
        elif re.search(r"required|must|ضروری|الزامی", line, re.I):
            rows.append(dict(text=line, priority="required", source="description"))
    for field in ["required_seniority", "required_education", "location"]:
        if job.get(field):
            rows.append(dict(text=job[field], source=field, priority="required"))
    output, seen = [], set()
    for row in rows:
        key = (normalize(row["text"]), row["priority"], row["source"])
        if key in seen:
            continue
        seen.add(key)
        tree, refs, status, reason = None, [], "unknown", "insufficient_evidence"
        try:
            if row["source"] in {"skills_required", "description"}:
                tree, years = expression(row["text"])
                tree = evaluate(tree, skills, bool(re.search(r"experience|تجربه|سابقه", row["text"], re.I)), years)
                tree["minimum_years"] = years
                status = tree["status"]
                refs = [
                    e
                    for s in skills
                    if s["name"] in {n[0] for n in mentions(row["text"])}
                    for r in s["observations"]
                    for e in r["evidence"]
                ]
                reason = "evaluated_expression"
            else:
                candidates = (
                    [r["fields"].get("job_title", {}) for r in structured.get("activities", [])]
                    if row["source"] == "required_seniority"
                    else (
                        [r["fields"].get("title", {}) for r in structured.get("education", [])]
                        if row["source"] == "required_education"
                        else [structured.get("identity", {}).get("location", {})]
                    )
                )
                wanted = normalize(row["text"])
                if row["source"] == "required_education" and wanted in {
                    "bachelor",
                    "bachelor's degree",
                    "bsc",
                    "کارشناسی",
                    "master",
                    "master's degree",
                    "msc",
                    "کارشناسی ارشد",
                    "phd",
                    "دکتری",
                }:
                    pattern = (
                        r"bachelor|\bbsc\b|کارشناسی(?! ارشد)"
                        if wanted in {"bachelor", "bachelor's degree", "bsc", "کارشناسی"}
                        else (
                            r"master|\bmsc\b|کارشناسی ارشد"
                            if wanted in {"master", "master's degree", "msc", "کارشناسی ارشد"}
                            else r"\bph\.?d\b|دکتری"
                        )
                    )
                    matches = [
                        r
                        for r in candidates
                        if re.search(pattern, normalize(r.get("value") or ""))
                        and not re.search(r"\bnot\b|\bno\b|فاقد|ندارد", normalize(r.get("value") or ""))
                    ]
                elif row["source"] == "required_seniority" and wanted in {
                    "senior",
                    "junior",
                    "lead",
                    "manager",
                    "intern",
                    "ارشد",
                    "مدیر",
                    "کارآموز",
                }:
                    matches = [
                        r
                        for r in candidates
                        if re.search(r"(?<!\w)" + re.escape(wanted) + r"(?!\w)", normalize(r.get("value") or ""))
                    ]
                elif row["source"] == "location":
                    matches = [
                        r
                        for r in candidates
                        if wanted in [x.strip() for x in normalize(r.get("value") or "").split(",")]
                    ]
                else:
                    matches = [r for r in candidates if wanted == normalize(r.get("value") or "")]
                if matches:
                    status, reason = "met", "exact_source_match"
                    refs = [e for r in matches for e in r.get("evidence", [])]
        except ValueError as error:
            reason = str(error)
        output.append(
            dict(
                **row,
                status=status,
                reason=reason,
                expression=tree,
                evidence=refs,
                skills=list(dict.fromkeys(n[0] for n in mentions(row["text"]))),
            )
        )
    contradictory = {s for r in output if r["reason"] == "negative_requirement" for s in r["skills"]}
    for row in output:
        if contradictory.intersection(row["skills"]):
            row.update(status="unknown", reason="conflicting_job_requirements")

    # شرط یکسان با متن متفاوت مخرج را چند برابر نمی‌کند؛ منابع هر دو باقی می‌مانند.
    def shape(tree):
        if not tree:
            return None
        if "operator" in tree:
            return [tree["operator"], sorted((shape(c) for c in tree["children"]), key=str), tree.get("minimum_years")]
        return [tree["skill"], tree.get("version"), tree.get("minimum_years")]

    deduplicated, seen_semantic = [], {}
    for row in output:
        key = json.dumps(shape(row["expression"]), sort_keys=True) if row["expression"] else row["text"]
        key = (key, row["priority"], row["status"])
        if key in seen_semantic:
            seen_semantic[key]["sources"].append(dict(text=row["text"], source=row["source"]))
        else:
            row["sources"] = [dict(text=row["text"], source=row["source"])]
            deduplicated.append(row)
            seen_semantic[key] = row
    return deduplicated
