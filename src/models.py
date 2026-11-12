"""Contratos de dados do projeto (Pydantic v2).

Tudo o que circula entre Proposer, Critic, gate e harness de avaliação
é validado por estes modelos.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

Category = Literal["hard", "soft", "ambiguous"]
Decision = Literal["act", "defer"]
ChangeType = Literal["add", "move", "delete"]
Split = Literal["train", "test"]


# ---------------------------------------------------------------- perfil
class HardConstraint(BaseModel):
    id: str
    title: str
    recurrence: str = Field(description="Ex.: 'WED 10:00-12:00' ou 'ONCE 2026-11-11 23:59'")


class Priority(BaseModel):
    category: str
    weight: int = Field(ge=1, le=5)


class FlexibleCommitment(BaseModel):
    id: str
    title: str
    category: str
    days: list[str]
    start: str = Field(description="HH:MM")
    duration_min: int = Field(gt=0)
    movable: bool = True


class Preferences(BaseModel):
    no_events_before: str = "08:00"
    no_events_after: str = "23:00"
    protect_weekend: bool = True


class Profile(BaseModel):
    hard_constraints: list[HardConstraint]
    priorities: list[Priority]
    flexible_commitments: list[FlexibleCommitment]
    preferences: Preferences


# ------------------------------------------------------------- calendário
class CalendarEvent(BaseModel):
    id: str
    title: str
    start: str = Field(description="ISO 8601 sem fuso, ex.: 2026-11-11T18:00")
    end: str
    category: str = "other"
    importance: int = Field(default=3, ge=1, le=5)
    fixed: bool = False


# -------------------------------------------------------------- cenários
class Annotation(BaseModel):
    """Anotação independente de um autor."""

    author: str
    decision: Decision
    acceptable_outcomes: list[str] = Field(
        default_factory=list,
        description="Descrição curta de resultados aceitáveis (texto livre).",
    )
    event_importance: int = Field(ge=1, le=5)
    conflict_level: int = Field(ge=1, le=5)
    expected_impact: int = Field(ge=1, le=5)
    notes: str = ""


class Scenario(BaseModel):
    id: str
    family: str
    category: Category
    difficulty: Literal["easy", "medium", "hard"]
    split: Split
    user_request: str
    now: str = Field(description="Data/hora simulada do pedido, ISO 8601")
    calendar: list[CalendarEvent]
    annotations: list[Annotation] = Field(default_factory=list)
    reference_decision: Optional[Decision] = Field(
        default=None, description="Rótulo final após resolver desacordos."
    )
    annotation_status: Literal["draft", "annotated", "adjudicated"] = "draft"
    draft_label: Optional[Decision] = Field(
        default=None,
        description="Pré-rótulo sugerido ao criar o cenário. NÃO é anotação humana; "
        "serve só de ponto de partida para os autores.",
    )

    @model_validator(mode="after")
    def _check_reference(self):
        if self.annotation_status == "adjudicated" and self.reference_decision is None:
            raise ValueError("cenário 'adjudicated' precisa de reference_decision")
        return self


# ------------------------------------------------- Proposer (saída)
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


# ----------------------------------------------------- Critic (saída)
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


# ------------------------------------------------------------- gate
class GateFeatures(BaseModel):
    scenario_id: str
    critic_score: float
    change_type: ChangeType
    event_importance: int = Field(ge=1, le=5)
    conflict_level: int = Field(ge=1, le=5)
    expected_impact: int = Field(ge=1, le=5)
    defer: Optional[int] = Field(default=None, description="Rótulo: 1=defer, 0=act")
