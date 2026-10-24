from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from ..models import EntityRef, Tag


class Candidate(BaseModel):
    """A recommendation to check: free-text name + domain (e.g. "movie").

    Set ``entity_id`` once a person has confirmed which entity an ambiguous
    name refers to.
    """
    name: str
    domain: str
    entity_id: str | None = None


class ResolutionStatus(str, Enum):
    resolved = "resolved"
    ambiguous = "ambiguous"
    cannot_verify = "cannot_verify"


class Resolution(BaseModel):
    status: ResolutionStatus
    entity: EntityRef | None = None
    options: list[EntityRef] = Field(default_factory=list)
    reason: str = ""


class Verdict(str, Enum):
    good = "good"
    weak = "weak"
    poor = "poor"
    needs_confirmation = "needs_confirmation"  # ambiguous name
    cannot_verify = "cannot_verify"


class Evidence(BaseModel):
    qloo_affinity: float | None = None          # Qloo insights affinity for this entity
    best_available_affinity: float | None = None  # top affinity Qloo returns for this profile+type
    relative_fit: float | None = None            # qloo_affinity / best_available (Hearth calc)
    shared_tags: list[Tag] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class Swap(BaseModel):
    entity: EntityRef
    qloo_affinity: float
    relative_fit: float
    shared_tags: list[Tag] = Field(default_factory=list)
    reason: str = ""


class CheckResult(BaseModel):
    candidate: Candidate
    resolution: Resolution
    verdict: Verdict
    evidence: Evidence = Field(default_factory=Evidence)
    swap: Swap | None = None


class VerifyReport(BaseModel):
    profile_name: str = ""
    results: list[CheckResult]
    counts: dict[str, int] = Field(default_factory=dict)
    source_note: str = ("Affinity and tags come from Qloo. Relative fit, verdict thresholds, "
                        "and feedback weights are Hearth calculations.")
