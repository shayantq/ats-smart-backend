"""بازبینی غایب یا ناسازگار، دقت انسانی یا کالیبراسیون ایجاد نمی‌کند."""

import pytest

from evaluation.phase4 import CASES, fingerprint, review_metrics, run


def test_rule_benchmark_and_unreviewed_denominator(tmp_path):
    result = run(tmp_path)
    assert result["correct"] == result["cases"] == 32
    assert result["independent_review"]["reviewed_denominator"] == 0
    assert result["independent_review"]["accuracy"] is None
    assert result["independent_review"]["calibrated"] is False


def test_independent_review_requires_two_reviewers_and_tracks_disagreement():
    case = CASES[0]
    base = dict(case_id=case[0], case_sha256=fingerprint(case), label="unmet", independent=True, evidence_checked=True)
    reviews = [dict(base, reviewer="hr-a"), dict(base, reviewer="hr-b")]
    assert review_metrics({case[0]: "unmet"}, reviews)["reviewed_denominator"] == 1
    reviews[1]["label"] = "unknown"
    result = review_metrics({case[0]: "unmet"}, reviews)
    assert result["reviewed_denominator"] == 0 and result["disagreement_cases"] == 1
    with pytest.raises(ValueError):
        review_metrics({}, [dict(base, reviewer="hr-a", independent=False)])
    with pytest.raises(ValueError):
        review_metrics({}, [reviews[0], reviews[0]])
