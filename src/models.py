"""Shared structured contracts for Proposer output and independent Critic output.

Scenario schema 2.0 lives in scenario_v2.py. Historical scenario/profile contracts
are preserved in archive/legacy_v1/src/models.py.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

ChangeType = Literal["add", "move", "delete"]


class Change(BaseModel):
    type: ChangeType
    event_id: Optional[str] = None
    title: Optional[str] = None
    from_start: Optional[str] = None
    to_start: Optional[str] = None
    to_end: Optional[str] = None

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


class CriticEvaluation(BaseModel):
    scores: CriticScores
    weaknesses: list[str]
    feedback: str

    @property
    def overall(self) -> float:
        s = self.scores
        return round((s.reasoning + s.coherence + s.alternatives + s.clarity) / 4, 2)
