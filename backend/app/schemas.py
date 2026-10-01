"""Pydantic models that define MedCloak's public API contract."""

from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field


EntityCategory = Literal[
    "NAME",
    "DATE",
    "PHONE",
    "EMAIL",
    "MRN",
    "PATIENT_ID",
    "ADDRESS",
    "POSTAL_CODE",
    "LOCATION",
    "ORGANIZATION",
]

PotentialPhiCategory = Literal[
    "NAME",
    "DATE",
    "PHONE",
    "EMAIL",
    "MRN",
    "PATIENT_ID",
    "ADDRESS",
    "POSTAL_CODE",
    "LOCATION",
    "ORGANIZATION",
    "OTHER",
]

RiskLevel = Literal["low", "medium", "high"]
PrivacyProfile = Literal["core", "strict"]
DeploymentMode = Literal["local", "hosted_demo"]


class DeidentifyRequest(BaseModel):
    """Text submitted for in-memory de-identification."""

    text: str = Field(min_length=1, max_length=20_000, description="Clinical note to redact.")
    privacy_profile: PrivacyProfile = "strict"


class DetectedEntity(BaseModel):
    """One identifier detected in the original note."""

    category: EntityCategory
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str
    replacement: str
    heuristic_score: float = Field(
        ge=0,
        le=1,
        description="Relative rule or detector priority; not a calibrated probability.",
    )
    detector: str


class DeidentifyResponse(BaseModel):
    """Redacted note plus a transparent audit trail."""

    redacted_text: str
    entities: list[DetectedEntity]
    category_counts: dict[str, int]
    review_required: bool
    privacy_notice: str


class PrivacyReviewRequest(BaseModel):
    """A first-pass redacted note sent to the local LLM reviewer only."""

    redacted_text: str = Field(min_length=1, max_length=20_000)


class ProtectedDocumentRequest(BaseModel):
    """Already-redacted text supplied for protected-file generation."""

    redacted_text: str = Field(min_length=1, max_length=20_000)


class PrivacyReviewFinding(BaseModel):
    """One possible identifier that the GenAI reviewer wants a human to inspect."""

    category: PotentialPhiCategory
    text: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=500)
    risk_level: RiskLevel


class PrivacyReviewResponse(BaseModel):
    """Structured output from the local GenAI privacy-review layer."""

    reviewer_model: str
    findings: list[PrivacyReviewFinding]
    review_required: bool = True
    safety_notice: str


class DemoNote(BaseModel):
    id: str
    title: str
    text: str


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    deployment_mode: DeploymentMode
    genai_review_available: bool


def category_counts(entities: list[DetectedEntity]) -> dict[str, int]:
    """Return a JSON-friendly summary for the audit panel."""

    return dict(Counter(entity.category for entity in entities))
