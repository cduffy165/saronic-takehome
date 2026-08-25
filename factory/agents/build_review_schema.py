"""Review's structured output schema."""

from typing import Literal

from pydantic import BaseModel

Severity = Literal["low", "medium", "high"]


class ReviewFinding(BaseModel):
    severity: Severity
    # Short label, e.g. "secrets", "injection", "missing_validation".
    category: str
    description: str


class ReviewResult(BaseModel):
    verdict: Literal["pass", "fail"]
    findings: list[ReviewFinding]
    summary: str


SUBMIT_REVIEW_TOOL = "submit_review"
