"""ورودی محدود بازبینی؛ هویت نویسنده و زمان از سرور گرفته می‌شوند."""

from typing import Literal
import re
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReviewEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["correction", "revoke", "note", "section_review", "shortlist", "feedback"]
    expected_revision: int = Field(ge=0)
    visibility: Literal["team", "private"] = "team"
    reason: str = Field(min_length=3, max_length=1000)
    target: str | None = Field(default=None, max_length=150)
    value: str | bool | None = None
    source_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    anchor: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    evidence_text: str | None = Field(default=None, max_length=2000)
    section: Literal["identity", "employment", "skills", "requirements", "education", "analysis"] | None = None

    @model_validator(mode="after")
    def validate_action(self):
        if not self.reason.strip():
            raise ValueError("review_reason_required")
        if self.action in {"correction", "revoke"}:
            if (
                self.visibility != "team"
                or not self.source_hash
                or not self.anchor
                or not self.target
                or not re.fullmatch(
                    r"identity\.(?:name|location)|activity:[A-Za-z0-9_-]+:"
                    r"(?:job_title|company|duration|location|client|engagement_type)",
                    self.target,
                )
            ):
                raise ValueError("invalid_correction_target")
        if self.action in {"correction", "note", "feedback"}:
            if not isinstance(self.value, str) or not self.value.strip() or len(self.value) > 4000:
                raise ValueError("review_text_required")
        if self.action == "correction" and (
            not self.evidence_text or not self.evidence_text.strip() or len(self.value) > 1000
        ):
            raise ValueError("correction_evidence_required")
        if self.action in {"section_review", "shortlist"} and not isinstance(self.value, bool):
            raise ValueError("boolean_review_required")
        if self.action == "section_review" and not self.section:
            raise ValueError("review_section_required")
        if self.action != "note" and self.visibility != "team":
            raise ValueError("only_notes_can_be_private")
        return self


class SelectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    application_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
