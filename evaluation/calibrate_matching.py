"""پیشنهاد نگاشت یکنواخت امتیاز با PAVA؛ هیچ وزن یا امتیاز محصول را فعال نمی‌کند."""

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path


def prepare(rows):
    groups = defaultdict(list)
    for row in rows:
        for key in ("case_id", "lineage", "reviewer"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError("missing_review_identity")
        if row.get("independent") is not True or row.get("evidence_checked") is not True:
            raise ValueError("independent_review_required")
        if row.get("split") not in {"development", "holdout"}:
            raise ValueError("invalid_split")
        for key in ("model_score", "hr_score"):
            value = row.get(key)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 100
            ):
                raise ValueError("invalid_score")
        groups[row["case_id"]].append(row)
    result = []
    for rows in groups.values():
        if len({r["reviewer"] for r in rows}) != len(rows) or len(rows) < 2:
            raise ValueError("two_distinct_reviewers_required")
        if len({(r["model_score"], r["split"], r["lineage"]) for r in rows}) != 1:
            raise ValueError("inconsistent_case_metadata")
        result.append(
            dict(
                score=rows[0]["model_score"],
                target=sum(r["hr_score"] for r in rows) / len(rows),
                split=rows[0]["split"],
                lineage=rows[0]["lineage"],
                reviewer_spread=max(r["hr_score"] for r in rows) - min(r["hr_score"] for r in rows),
            )
        )
    a = {r["lineage"] for r in result if r["split"] == "development"}
    b = {r["lineage"] for r in result if r["split"] == "holdout"}
    if a & b:
        raise ValueError("lineage_leakage")
    return result


def fit(rows):
    scores = defaultdict(list)
    for row in rows:
        scores[row["score"]].append(row["target"])
    if len(scores) < 2:
        raise ValueError("two_distinct_training_scores_required")
    blocks = []
    for x, ys in sorted(scores.items()):
        blocks.append(dict(low=x, high=x, total=sum(ys), weight=len(ys)))
        while (
            len(blocks) > 1 and blocks[-2]["total"] / blocks[-2]["weight"] > blocks[-1]["total"] / blocks[-1]["weight"]
        ):
            right, left = blocks.pop(), blocks.pop()
            blocks.append(
                dict(
                    low=left["low"],
                    high=right["high"],
                    total=left["total"] + right["total"],
                    weight=left["weight"] + right["weight"],
                )
            )
    return [dict(low=b["low"], high=b["high"], value=b["total"] / b["weight"]) for b in blocks]


def predict(blocks, score):
    for block in blocks:
        if score <= block["high"]:
            return block["value"]
    return blocks[-1]["value"]


def proposal(rows):
    prepared = prepare(rows)
    train = [r for r in prepared if r["split"] == "development"]
    test = [r for r in prepared if r["split"] == "holdout"]
    if not test:
        raise ValueError("independent_holdout_required")
    blocks = fit(train)
    before = sum(abs(r["score"] - r["target"]) for r in test) / len(test)
    after = sum(abs(predict(blocks, r["score"]) - r["target"]) for r in test) / len(test)
    return dict(
        version="matching-calibration-proposal-v1",
        method="isotonic_pava_step_v1",
        blocks=blocks,
        development_cases=len(train),
        holdout_cases=len(test),
        holdout_mae_before=before,
        holdout_mae_after=after,
        improves_holdout=after < before,
        max_reviewer_spread=max(r["reviewer_spread"] for r in prepared),
        source_sha256=hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
        activated=False,
        production_qualified=False,
        limitations=[
            "independence_attested_by_input",
            "sample_size_and_representativeness_require_review",
            "hr_rating_is_not_hiring_outcome",
            "no_fairness_or_external_validity_claim",
        ],
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("training/reports/phase4-v2/calibration-proposal.json"))
    args = parser.parse_args()
    report = proposal(json.loads(args.input.read_text(encoding="utf8")))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf8")
    print(
        json.dumps({k: report[k] for k in ["development_cases", "holdout_cases", "activated", "production_qualified"]})
    )
