"""قرارداد نسخه‌دار برچسب‌ها و جداسازی lineage."""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    fields: dict[str, str | float | bool | None]
    evidence: list[str] = Field(default_factory=list)
    evidence_refs: list[dict[str, int]] = Field(default_factory=list)


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal["resume-eval-v1"] = "resume-eval-v1"
    id: str
    lineage: str
    language: Literal["fa", "en", "mixed"]
    layout: Literal["single", "columns", "table"]
    input_type: Literal["text", "image", "hybrid", "corrupt"]
    pages: list[list[str]]
    expected: list[Record]
    sections: list[str]
    precision: dict[str, str] = Field(default_factory=dict)
    expected_error: str | None = None
    duration_range_years: tuple[float, float] | None = None
    review: Literal["author_draft", "independent_reviewed"] = "author_draft"
    reviewer: str | None = None


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_corpus(cases, dev, holdout, frozen_hash):
    ids = {c.id for c in cases}
    assert len(ids) == len(cases), "duplicate_case_id"
    assert set(dev).isdisjoint(holdout) and set(dev) | set(holdout) == ids, "invalid_split"
    by_id = {c.id: c for c in cases}
    assert {by_id[x].lineage for x in dev}.isdisjoint({by_id[x].lineage for x in holdout}), "lineage_leak"
    # شباهت قالب به معنی یکسانی محتوا نیست؛ متن یکسان یا تغییر صرفِ تصویر/متن نباید نشت کند.
    texts = [digest(c.pages) for c in cases]
    for i, a in enumerate(cases):
        for j, b in enumerate(cases[:i]):
            if texts[i] == texts[j]:
                assert a.lineage == b.lineage, "untracked_duplicate"
    assert digest([by_id[x].model_dump() for x in holdout]) == frozen_hash, "holdout_changed"
    from evaluation.resumes.metrics import norm

    def profile(c):
        # تغییر نام یا قالب، رزومهٔ مستقل برای holdout تولید نمی‌کند.
        return digest(
            sorted(
                (
                    r.kind,
                    sorted(
                        (k, str(norm(v)))
                        for k, v in r.fields.items()
                        if k not in {"name", "email", "phone", "company", "university"}
                    ),
                )
                for r in c.expected
                if r.kind != "identity"
            )
        )

    for a in (by_id[x] for x in dev):
        for b in (by_id[x] for x in holdout):
            assert profile(a) != profile(b), "near_duplicate_profile_leak"
    for c in cases:
        assert c.review != "independent_reviewed" or c.reviewer, "reviewer_missing"
        assert c.pages or c.expected_error, "source_missing"
        source = "\n".join(line for page in c.pages for line in page)
        for r in c.expected:
            assert all(e in source for e in r.evidence), "evidence_not_in_source"
            assert r.evidence, "label_evidence_missing"
            for value in r.fields.values():
                if isinstance(value, str):
                    assert norm(value) in norm("\n".join(r.evidence)), "label_value_not_supported"
            for ref in r.evidence_refs:
                assert 1 <= ref["page"] <= len(c.pages), "invalid_page_ref"
                assert 1 <= ref["line"] <= len(c.pages[ref["page"] - 1]), "invalid_line_ref"
    return True
