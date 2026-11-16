"""اعداد این تست ساختگی‌اند و بازبینی HR واقعی محسوب نمی‌شوند."""

import pytest

from evaluation.calibrate_matching import fit, proposal


def reviews():
    return [
        dict(
            case_id=str(i),
            lineage=str(i),
            reviewer=reviewer,
            independent=True,
            evidence_checked=True,
            split="development" if i < 2 else "holdout",
            model_score=x,
            hr_score=y,
        )
        for i, (x, y) in enumerate([(10, 20), (80, 90), (50, 55)])
        for reviewer in ["synthetic-a", "synthetic-b"]
    ]


def test_pava_pools_decreasing_observations_and_does_not_activate():
    assert fit([dict(score=1, target=3), dict(score=2, target=1), dict(score=3, target=2)]) == [
        dict(low=1, high=2, value=2),
        dict(low=3, high=3, value=2),
    ]
    r = proposal(reviews())
    assert r["development_cases"] == 2 and r["holdout_cases"] == 1
    assert not r["activated"] and not r["production_qualified"]


def test_rejects_unreviewed_duplicate_leakage_and_nonfinite_scores():
    for mutate in [
        lambda r: r[0].update(independent=False),
        lambda r: r[1].update(reviewer="synthetic-a"),
        lambda r: r[-1].update(lineage="0"),
        lambda r: r[0].update(hr_score=float("nan")),
    ]:
        rows = reviews()
        mutate(rows)
        with pytest.raises(ValueError):
            proposal(rows)
