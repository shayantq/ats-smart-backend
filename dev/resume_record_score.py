import json
import sys
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.resume_dates import date_range, endpoint, normalize
from app.model_inference.resume_digest import iter_records
from dev.resume_digest_measure import sample_file, sample_root

RecordType = Literal["job", "teaching", "project", "certificate", "education", "honor", "membership", "internship"]
_TYPES = ("job", "teaching", "project", "certificate", "education", "honor", "membership", "internship")


class ReferenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    type: RecordType
    organization: str | None
    title: str
    start: str | None
    end: str | None
    page: int = Field(ge=1)


class HumanReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    review_status: Literal["human_reviewed", "draft_unreviewed"]
    records: list[ReferenceRecord]


def _window(start: str | None, end: str | None, reference: date):
    if not (start or end):
        return None
    try:
        low = endpoint(start or end, reference)[0]
        high = endpoint(end or start, reference)[1]
    except (ValueError, TypeError):
        return None
    return (low, high) if low <= high else None


def _predictions(structured: dict, reference: date):
    for _, kind, record in iter_records(structured):
        kind = "job" if kind in {"employment", "freelance"} else kind
        if kind not in _TYPES:
            continue
        fields = record.get("fields") or {}

        def get(*keys):
            return next((fields[key]["value"] for key in keys if (fields.get(key) or {}).get("value")), "")

        dates = record.get("dates") or date_range(get("duration", "date"), reference)
        if dates["status"] == "valid":
            interval = _window(dates["start"]["earliest"], dates["end"]["latest"], reference)
        else:
            interval = _window(get("date"), None, reference)
        yield kind, normalize(get("company", "institution", "organization")), normalize(
            get("job_title", "project_name", "title")
        ), interval


def _match_count(predictions, truth):
    occupied = {}
    neighbors = []
    for _, organization, title, bounds in predictions:
        candidates = []
        for index, (_, expected_org, expected_title, expected_bounds) in enumerate(truth):
            if organization != expected_org or (not organization and (not title or title != expected_title)):
                continue
            if bounds and expected_bounds and max(bounds[0], expected_bounds[0]) <= min(bounds[1], expected_bounds[1]):
                candidates.append((title != expected_title, index))
        neighbors.append([index for _, index in sorted(candidates)])

    for prediction, _ in enumerate(neighbors):
        pending, parents = [prediction], {}
        for node in pending:
            for index in neighbors[node]:
                if index in parents:
                    continue
                parents[index] = node
                if index not in occupied:
                    break
                pending.append(occupied[index])
            else:
                continue
            break
        else:
            continue
        previous = {node: index for index, node in occupied.items()}
        while index is not None:
            node = parents[index]
            occupied[index] = node
            index = previous.get(node)
    return len(occupied)


def score_records(structured: dict, reference: HumanReference, *, as_of: date | None = None) -> dict:
    if reference.review_status != "human_reviewed":
        return {"scored": 0, "draft_excluded": 1}
    as_of = as_of or date.today()
    predictions = list(_predictions(structured, as_of))
    truth = [
        (row.type, normalize(row.organization or ""), normalize(row.title), _window(row.start, row.end, as_of))
        for row in reference.records
    ]
    result = {}
    for kind in _TYPES:
        actual = [row for row in predictions if row[0] == kind]
        expected = [row for row in truth if row[0] == kind]
        matched = _match_count(actual, expected)
        result[kind] = {
            "matched": matched,
            "expected": len(expected),
            "predicted": len(actual),
            "expected_without_dates": sum(row[3] is None for row in expected),
            "predicted_without_dates": sum(row[3] is None for row in actual),
            "recall": matched / len(expected) if expected else None,
            "precision": matched / len(actual) if actual else None,
        }
    return {"scored": 1, "record_types": result}


def main() -> int:
    try:
        root = sample_root()
        if root is None or len(sys.argv) != 3:
            raise ValueError("invalid_score_arguments")
        parsed = json.loads(sample_file(root, Path(sys.argv[1])).read_text(encoding="utf-8"))
        reference = HumanReference.model_validate_json(sample_file(root, Path(sys.argv[2])).read_bytes())
        result = score_records(parsed.get("structured", parsed), reference)
    except Exception:
        print(json.dumps({"scored": 0, "input_error": 1}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
