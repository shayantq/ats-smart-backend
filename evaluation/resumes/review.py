"""دفتر بازبینی append-only؛ برچسب مرجع و holdout را بازنویسی نمی‌کند."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from evaluation.resumes.contract import digest
from evaluation.resumes.run import load


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--decision", choices=["approve", "reject"], required=True)
    parser.add_argument("--attest-independent-review", action="store_true", required=True)
    parser.add_argument("--ledger", type=Path, default=Path("training/reports/resume-eval-reviews.jsonl"))
    args = parser.parse_args()
    case = next((c for c in load()[0] if c.id == args.case), None)
    if case is None:
        parser.error("unknown_case")
    entry = dict(
        case_id=case.id,
        case_sha256=digest(case.model_dump()),
        reviewer_alias=args.reviewer,
        decision=args.decision,
        independent_review_attested=True,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    with args.ledger.open("a", encoding="utf8") as stream:
        stream.write(json.dumps(entry) + "\n")
    print("review recorded; frozen labels unchanged")


if __name__ == "__main__":
    main()
