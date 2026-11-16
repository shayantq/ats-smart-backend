"""اصلاح محافظت‌شده و نسخهٔ منبع با دادهٔ ساختگی."""

import copy

import pytest
from pydantic import ValidationError

from app.core.dossier_review import replay, target_fact, compare_payloads, digest
from app.schemas.dossier_review import ReviewEventInput


def parsed():
    return {
        "_extraction": {"file_sha256": "a" * 64},
        "structured": {
            "identity": {"name": {"value": "MIRA HART", "status": "extracted", "evidence": [{"text": "MIRA HART"}]}},
            "activities": [],
        },
    }


def test_correction_preserves_original_and_survives_identical_source_reanalysis():
    source = parsed()
    original = copy.deepcopy(source)
    fact, anchor = target_fact(source, "identity.name")
    event = dict(
        id="event",
        action="correction",
        payload=dict(
            target="identity.name",
            source_hash="a" * 64,
            anchor=anchor,
            value="Mira Hart",
            evidence_text="Visual review",
        ),
    )
    for _ in range(2):
        result = replay(source, [event])
        assert result["effective_parsed"]["structured"]["identity"]["name"]["value"] == "Mira Hart"
        assert result["corrections"][0]["applicable"]
        assert source == original
    source["_extraction"]["file_sha256"] = "b" * 64
    assert not replay(source, [event])["corrections"][0]["applicable"]


def test_rejection_of_account_edit_missing_evidence_and_private_correction():
    base = dict(
        action="correction",
        expected_revision=0,
        reason="review",
        source_hash="a" * 64,
        anchor="b" * 64,
        value="Fixed",
        evidence_text="source",
    )
    for change in [
        dict(target="account.name"),
        dict(target="identity.name", visibility="private"),
        dict(target="identity.name", evidence_text=""),
    ]:
        with pytest.raises(ValidationError):
            ReviewEventInput(**(base | change))


def test_revision_comparison_never_compares_unrelated_policies():
    a = dict(
        source_hash="a",
        analysis_version="v1",
        job_sha256="job1",
        parsed_data={"_evidence_analysis": {"coverage": {"weighting": "equal-v1"}}},
    )
    assert not compare_payloads(a, a | dict(job_sha256="job2"))["comparable"]
    assert compare_payloads(a, a)["comparable"]
    assert compare_payloads(a, a | dict(source_hash="b"))["score_delta"] is None


def test_review_attestation_expires_after_reanalysis_or_later_correction():
    source = parsed()
    event = dict(
        id="attestation",
        action="section_review",
        payload=dict(section="identity", value=True, source_hash="a" * 64, analysis_fingerprint=digest(source)),
    )
    assert replay(source, [event])["sections"]["identity"]["current"]
    changed = copy.deepcopy(source)
    changed["_evidence_analysis"] = {"version": "new"}
    assert not replay(changed, [event])["sections"]["identity"]["current"]
    _, anchor = target_fact(source, "identity.name")
    correction = dict(
        id="change",
        action="correction",
        payload=dict(
            target="identity.name", anchor=anchor, source_hash="a" * 64, value="New name", evidence_text="Source review"
        ),
    )
    assert not replay(source, [event, correction])["sections"]["identity"]["current"]


def test_recorded_score_delta_requires_complete_source_and_compatible_policy():
    base = dict(
        analysis_version="v1",
        job_sha256="job",
        analysis={"matching": {"score": 40}},
        parsed_data={"_extraction": {"status": "completed"}, "_evidence_analysis": {"coverage": {"weighting": "v1"}}},
    )
    assert compare_payloads(base, base | {"analysis": {"matching": {"score": 55}}})["score_delta"] == 15
    assert compare_payloads(base, base | {"job_sha256": "other"})["score_delta"] is None


def test_version_diff_preserves_old_and_new_values_and_source_evidence():
    before = {"parsed_data": parsed()}
    after = copy.deepcopy(before)
    after["parsed_data"]["structured"]["identity"]["name"]["value"] = "Mira Hart"
    differences = compare_payloads(before, after)
    name = next(c for c in differences["field_changes"] if c["field"] == "identity.name")
    assert name["before"]["value"] == "MIRA HART" and name["after"]["value"] == "Mira Hart"
    assert name["before"]["evidence"] == ["MIRA HART"]


def test_waiting_queue_is_not_reported_as_expired_processing():
    from app.tasks.resume_model import public_state

    assert public_state({"status": "queued", "expires_at": 0})["status"] == "queued"
