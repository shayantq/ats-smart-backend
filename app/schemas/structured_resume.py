"""قرارداد افزایشی فاز ۳؛ تأیید منبع با تأیید اصالت ادعا متفاوت است."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Evidence(BaseModel):
    text: str
    page: int | None = None
    bbox: list[float] | None = None
    block_id: str | None = None


class Fact(BaseModel):
    value: str | None = None
    status: Literal["extracted", "ambiguous", "missing", "invalid", "attributed"] = "missing"
    evidence: list[Evidence] = Field(default_factory=list)
    reason: str | None = None

    @model_validator(mode="after")
    def require_source(self):
        if self.value is not None and (not self.evidence or not any(ref.text.strip() for ref in self.evidence)):
            raise ValueError("fact_requires_evidence")
        if self.status == "missing" and self.value is not None:
            raise ValueError("missing_fact_cannot_have_value")
        return self


class Activity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: Literal["employment", "internship", "freelance", "volunteering", "project", "teaching"]
    fields: dict[str, Fact]
    dates: dict
    claims: list[Fact] = Field(default_factory=list)
    source: Literal["resume_evidence_v3"] = "resume_evidence_v3"


class StructuredResume(BaseModel):
    version: Literal["resume-structured-v1"] = "resume-structured-v1"
    source_sha256: str
    reference_date: str
    identity: dict[str, Fact]
    contacts: list[Fact]
    links: list[Fact]
    activities: list[Activity]
    education: list[dict]
    certifications: list[dict]
    languages: list[dict]
    publications: list[dict]
    awards: list[dict]
    totals: dict
    overlaps: list[dict]
    gaps: list[dict]
    warnings: list[str]
