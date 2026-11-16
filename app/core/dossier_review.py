"""بازپخش وقایع بدون دست‌کاری دادهٔ اصلی؛ اصلاح روی منبع نامنطبق اعمال نمی‌شود."""

import copy
import hashlib
import json
import math


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def source_hash(parsed):
    return ((parsed or {}).get("_extraction") or {}).get("file_sha256")


def target_fact(parsed, target):
    structured = (parsed or {}).get("structured") or {}
    if target.startswith("identity."):
        key = target.split(".", 1)[1]
        record = structured.get("identity") or {}
        return record.get(key), digest(record)
    kind, identifier, key = target.split(":")
    if kind != "activity":
        return None, None
    record = next((a for a in structured.get("activities", []) if a["id"] == identifier), None)
    if record is None:
        return None, None
    return record["fields"].get(key), digest(record["fields"])


def replay(parsed, events):
    effective = copy.deepcopy(parsed or {})
    latest, sections, notes, feedback = {}, {}, [], []
    shortlisted = False
    for event in events:
        payload = event["payload"]
        if event["action"] in {"correction", "revoke"}:
            latest[payload["target"]] = event
            for reviewed in sections.values():
                reviewed["current"] = False
        elif event["action"] == "section_review":
            sections[payload["section"]] = dict(
                verified=payload["value"],
                source_hash=payload.get("source_hash"),
                event_id=event["id"],
                current=(
                    payload.get("source_hash") == source_hash(parsed)
                    and payload.get("analysis_fingerprint") == digest(parsed or {})
                ),
            )
        elif event["action"] == "note":
            notes.append(event)
        elif event["action"] == "shortlist":
            shortlisted = payload["value"]
        elif event["action"] == "feedback":
            feedback.append(event)
    corrections = []
    for target, event in latest.items():
        payload = event["payload"]
        original, anchor = target_fact(parsed, target)
        applicable = bool(
            original is not None
            and payload.get("source_hash") == source_hash(parsed)
            and payload.get("anchor") == anchor
        )
        correction = dict(event, applicable=applicable, revoked=event["action"] == "revoke", original=original)
        corrections.append(correction)
        if not applicable or event["action"] == "revoke":
            continue
        replacement = dict(
            original,
            value=payload["value"],
            status="attributed",
            reason="human_correction",
            evidence=[dict(text=payload["evidence_text"])],
            review_event_id=event["id"],
        )
        if target.startswith("identity."):
            effective["structured"]["identity"][target.split(".")[1]] = replacement
        else:
            _, identifier, key = target.split(":")
            activity = next(a for a in effective["structured"]["activities"] if a["id"] == identifier)
            activity["fields"][key] = replacement
            # محاسبهٔ تاریخ و امتیاز قبلی را با ویرایش انسانی معتبر جلوه نمی‌دهیم.
            if key == "duration":
                activity["dates"] = dict(status="unknown", source=payload["value"], start=None, end=None, ongoing=False)
    if any(c["applicable"] and not c["revoked"] for c in corrections):
        effective["_review_warning"] = "human_corrections_require_derived_analysis_review"
        structured = effective.get("structured") or {}
        if any(
            c["applicable"] and not c["revoked"] and c["payload"]["target"].endswith(":duration") for c in corrections
        ):
            structured.update(totals={}, overlaps=[], gaps=[])
        if effective.get("_evidence_analysis"):
            effective["_evidence_analysis"]["stale_after_human_review"] = True
            effective["_evidence_analysis"]["coverage"] = dict(
                lower=None, upper=None, denominator=0, calibrated=False, suppressed_reason="human_review_changed_source"
            )
    return dict(
        effective_parsed=effective,
        corrections=corrections,
        sections=sections,
        notes=notes,
        feedback=feedback,
        shortlisted=shortlisted,
    )


def snapshot_payload(resume, context, analysis, metrics):
    parsed = copy.deepcopy(resume.parsed_data or {})
    return dict(
        version="dossier-snapshot-v1",
        parsed_data=parsed,
        analysis=analysis,
        job_context=copy.deepcopy(context or {}),
        source_hash=source_hash(parsed),
        analysis_version=(parsed.get("_evidence_analysis") or {}).get("version"),
        job_sha256=(parsed.get("_evidence_analysis") or {}).get("job_sha256"),
        metrics=metrics,
    )


def compare_payloads(a, b):
    keys = ["source_hash", "analysis_version", "job_sha256"]
    changed = [key for key in keys if a.get(key) != b.get(key)]

    def policy(payload):
        profile = (payload.get("parsed_data") or {}).get("_evidence_analysis") or {}
        return (profile.get("coverage") or {}).get("weighting")

    compatible = bool(
        a.get("analysis_version")
        and a.get("job_sha256")
        and policy(a)
        and not any(k in changed for k in ["analysis_version", "job_sha256"])
        and policy(a) == policy(b)
    )
    fields = []
    for key in ["identity", "activities", "education", "languages"]:
        left = ((a.get("parsed_data") or {}).get("structured") or {}).get(key)
        right = ((b.get("parsed_data") or {}).get("structured") or {}).get(key)
        if left != right:
            fields.append(key)
    score_a = (a.get("analysis") or {}).get("matching", {}).get("score")
    score_b = (b.get("analysis") or {}).get("matching", {}).get("score")
    quality = all(((p.get("parsed_data") or {}).get("_extraction") or {}).get("status") == "completed" for p in [a, b])
    delta = (
        score_b - score_a
        if compatible
        and quality
        and all(
            isinstance(s, (int, float)) and not isinstance(s, bool) and math.isfinite(s) for s in [score_a, score_b]
        )
        else None
    )

    def facts(payload):
        structured = (payload.get("parsed_data") or {}).get("structured") or {}
        result = {}
        labels = {
            "name": "نام فایل",
            "location": "مکان",
            "job_title": "عنوان فعالیت",
            "company": "شرکت",
            "duration": "تاریخ فعالیت",
            "client": "مشتری",
            "engagement_type": "نوع همکاری",
        }

        def add(key, label, fact):
            if isinstance(fact, dict):
                result[key] = dict(
                    label=label,
                    value=fact.get("value"),
                    status=fact.get("status"),
                    evidence=[e.get("text") for e in fact.get("evidence", [])[:3] if isinstance(e, dict)],
                )

        for key in ("name", "location"):
            add("identity." + key, labels[key], (structured.get("identity") or {}).get(key))
        for activity in structured.get("activities", []):
            for key, fact in activity.get("fields", {}).items():
                if key in labels:
                    add(f"activity:{activity.get('id')}:{key}", labels[key], fact)
        return result

    before, after = facts(a), facts(b)
    changed_facts = [
        dict(field=key, label=(after.get(key) or before[key])["label"], before=before.get(key), after=after.get(key))
        for key in sorted(before.keys() | after.keys())
        if before.get(key) != after.get(key)
    ]

    def requirements(payload):
        profile = (payload.get("parsed_data") or {}).get("_evidence_analysis") or {}
        return {r["text"]: r for r in profile.get("requirements", []) if isinstance(r, dict) and r.get("text")}

    old_requirements, new_requirements = requirements(a), requirements(b)
    requirement_changes = [
        dict(text=key, before=old_requirements.get(key), after=new_requirements.get(key))
        for key in sorted(old_requirements.keys() | new_requirements.keys())
        if old_requirements.get(key) != new_requirements.get(key)
    ]
    return dict(
        changed=changed,
        changed_sections=fields,
        comparable=compatible,
        score_delta=delta,
        field_changes=changed_facts[:50],
        field_changes_truncated=len(changed_facts) > 50,
        requirement_changes=requirement_changes[:50],
        requirement_changes_truncated=len(requirement_changes) > 50,
        reason="same_policy_evidence_comparison" if compatible else "different_job_or_analysis_policy",
    )
