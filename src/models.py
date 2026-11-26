"""Shared structured contracts for Proposer output and independent Critic output.

Scenario schema 2.0 lives in scenario_v2.py. Historical scenario/profile contracts
are preserved in archive/legacy_v1/src/models.py.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

ChangeType = Literal["add", "move", "delete"]


class Change(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "allOf": [{
            "if": {"properties": {"type": {"enum": ["move", "delete"]}},
                   "required": ["type"]},
            "then": {"properties": {
                "category": {"type": "null"},
                "importance": {"type": "null"},
                "participants": {"type": "null"},
            }},
        }]
    })

    type: ChangeType
    event_id: Optional[str] = None
    title: Optional[str] = None
    from_start: Optional[str] = None
    to_start: Optional[str] = None
    to_end: Optional[str] = None
    category: Optional[str] = Field(
        default=None, description="Only valid for add; use null for move or delete."
    )
    importance: Optional[int] = Field(
        default=None, ge=1, le=5,
        description="Only valid for add; use null for move or delete.",
    )
    participants: Optional[list[str]] = Field(
        default=None, description="Only valid for add; use null for move or delete."
    )

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


# Compact, versioned IAedu wire contract. The rest of the application continues
# to consume the canonical Proposal above, including historical run artifacts.
PROPOSER_WIRE_SCHEMA_VERSION = "compact_proposal_v2"
BriefConstraint = Annotated[str, Field(min_length=1, max_length=120)]
BriefPriority = Annotated[str, Field(min_length=1, max_length=100)]


class ProposerWireAdd(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    op: Literal["add"] = Field(alias="o")
    title: str = Field(min_length=1, max_length=100, alias="t")
    start: str = Field(min_length=1, alias="s")
    end: str | None = Field(default=None, alias="e")
    event_id: str | None = Field(default=None, alias="i")
    category: str | None = Field(default=None, alias="c")
    importance: int | None = Field(default=None, ge=1, le=5, alias="w")
    participants: list[str] | None = Field(default=None, max_length=8, alias="p")


class ProposerWireMove(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    op: Literal["move"] = Field(alias="o")
    event_id: str = Field(min_length=1, alias="i")
    start: str = Field(min_length=1, alias="s")
    end: str | None = Field(default=None, alias="e")


class ProposerWireDelete(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    op: Literal["delete"] = Field(alias="o")
    event_id: str = Field(min_length=1, alias="i")


ProposerWireChange = Annotated[
    ProposerWireAdd | ProposerWireMove | ProposerWireDelete,
    Field(discriminator="op"),
]


class ProposerWireAlternative(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    option: str = Field(min_length=1, max_length=80, alias="o")
    reason: str = Field(min_length=1, max_length=120, alias="r")


class ProposerWireRationale(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    constraints: list[BriefConstraint] = Field(max_length=6, alias="c")
    priorities: list[BriefPriority] = Field(max_length=5, alias="p")
    alternatives: list[ProposerWireAlternative] = Field(max_length=3, alias="a")
    summary: str = Field(min_length=1, max_length=300, alias="s")


class ProposerWireProposal(BaseModel):
    """Compact model-facing representation normalized to canonical Proposal."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    changes: list[ProposerWireChange] = Field(max_length=16, alias="c")
    rationale: ProposerWireRationale = Field(alias="r")

    def to_proposal(self) -> Proposal:
        changes: list[Change] = []
        for item in self.changes:
            if isinstance(item, ProposerWireAdd):
                changes.append(Change(
                    type="add", event_id=item.event_id, title=item.title,
                    to_start=item.start, to_end=item.end, category=item.category,
                    importance=item.importance, participants=item.participants,
                ))
            elif isinstance(item, ProposerWireMove):
                changes.append(Change(
                    type="move", event_id=item.event_id,
                    to_start=item.start, to_end=item.end,
                ))
            else:
                changes.append(Change(type="delete", event_id=item.event_id))
        return Proposal(
            changes=changes,
            rationale=Rationale(
                constraints=self.rationale.constraints,
                priorities=self.rationale.priorities,
                alternatives_considered=[Alternative(
                    option=item.option, rejected_because=item.reason,
                ) for item in self.rationale.alternatives],
                summary=self.rationale.summary,
            ),
        )

    @classmethod
    def from_proposal(cls, proposal: Proposal) -> "ProposerWireProposal":
        wire_changes = []
        for item in proposal.changes:
            if item.type == "add":
                wire_changes.append(ProposerWireAdd(
                    op="add", event_id=item.event_id, title=item.title,
                    start=item.to_start, end=item.to_end, category=item.category,
                    importance=item.importance, participants=item.participants,
                ))
            elif item.type == "move":
                wire_changes.append(ProposerWireMove(
                    op="move", event_id=item.event_id,
                    start=item.to_start, end=item.to_end,
                ))
            else:
                wire_changes.append(ProposerWireDelete(op="delete", event_id=item.event_id))
        return cls(
            changes=wire_changes,
            rationale=ProposerWireRationale(
                constraints=proposal.rationale.constraints,
                priorities=proposal.rationale.priorities,
                alternatives=[ProposerWireAlternative(
                    option=item.option, reason=item.rejected_because,
                ) for item in proposal.rationale.alternatives_considered],
                summary=proposal.rationale.summary,
            ),
        )


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
