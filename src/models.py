"""Shared structured contracts for Proposer output and independent Critic output.

Scenario schema 2.0 lives in scenario_v2.py. Historical scenario/profile contracts
are preserved in archive/legacy_v1/src/models.py.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

ChangeType = Literal["add", "move", "delete"]


class Change(BaseModel):
    type: ChangeType
    event_id: Optional[str] = None
    title: Optional[str] = None
    from_start: Optional[str] = None
    to_start: Optional[str] = None
    to_end: Optional[str] = None
    category: Optional[str] = None
    importance: Optional[int] = Field(default=None, ge=1, le=5)
    participants: Optional[list[str]] = None

    @model_validator(mode="after")
    def _required_fields(self):
        required = {
            "add": ("title", "to_start"),
            "move": ("event_id", "to_start"),
            "delete": ("event_id",),
        }[self.type]
        missing = [field for field in required
                   if not isinstance(getattr(self, field), str) or not getattr(self, field).strip()]
        if missing:
            raise ValueError(f"{self.type} requer: {', '.join(missing)}")
        if self.category is not None and (self.type != "add" or not self.category.strip()):
            raise ValueError("category is only allowed on add and must be nonempty")
        if self.participants is not None and (self.type != "add" or len(self.participants) != len(set(self.participants)) or any(not p.strip() for p in self.participants)):
            raise ValueError("participants are only allowed on add and must be unique nonempty strings")
        if self.importance is not None and self.type != "add":
            raise ValueError("importance is only allowed on add")
        return self


class Alternative(BaseModel):
    option: str
    rejected_because: str


class Rationale(BaseModel):
    constraints: list[str]
    priorities: list[str]
    alternatives_considered: list[Alternative]
    summary: str


class Proposal(BaseModel):
    changes: list[Change]
    rationale: Rationale


class CriticScores(BaseModel):
    reasoning: int = Field(ge=1, le=5)
    coherence: int = Field(ge=1, le=5)
    alternatives: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)


class PlausibilityReview(BaseModel):
    """Contextual recommendation; severity alone never decides revision."""
    model_config = ConfigDict(extra="forbid")

    revision_required: StrictBool
    severity: Literal["none", "low", "moderate", "high"]
    reason: str
    suggested_improvement: str

    @model_validator(mode="after")
    def consistent_revision(self):
        if self.revision_required:
            if self.severity in {"none", "low"}:
                raise ValueError("required revision needs moderate or high severity")
            if not self.reason.strip() or not self.suggested_improvement.strip():
                raise ValueError("required revision needs evidence and an actionable suggestion")
        elif self.severity != "none" and not self.reason.strip():
            raise ValueError("observed plausibility risk needs a reason")
        return self


class UnresolvedAssumption(BaseModel):
    """Unverified condition, never an autonomy decision or technical violation."""
    model_config = ConfigDict(extra="forbid")

    subject: str
    assumption: str
    evidence_gap: str
    potential_impact: Literal["minor", "material", "potentially_blocking"]
    verification_source: Literal["external_source", "user_context", "third_party", "unknown"]

    @model_validator(mode="after")
    def concrete_description(self):
        if not all(value.strip() for value in (self.subject, self.assumption, self.evidence_gap)):
            raise ValueError("unresolved assumption needs subject, condition and evidence gap")
        return self


class CriticEvaluation(BaseModel):
    """Read historical responses; absence means not assessed, never no risk."""
    scores: CriticScores
    weaknesses: list[str]
    feedback: str
    plausibility_review: PlausibilityReview | None = None
    unresolved_assumptions: list[UnresolvedAssumption] | None = None

    @property
    def overall(self) -> float:
        s = self.scores
        return round((s.reasoning + s.coherence + s.alternatives + s.clarity) / 4, 2)


class PlausibilityCriticEvaluation(CriticEvaluation):
    """Required fields in historical plausibility_review_v1 responses."""
    model_config = ConfigDict(extra="forbid")
    plausibility_review: PlausibilityReview


class CurrentCriticEvaluation(PlausibilityCriticEvaluation):
    """New uncertainty_review_v2 response; [] explicitly means none identified."""
    unresolved_assumptions: list[UnresolvedAssumption]
