"""Critic independente: observa apenas a proposta e a sua justificação."""
from __future__ import annotations

from llm import Provider, get_provider
from models import CriticEvaluation, Proposal


SYSTEM = """You are an independent reviewer of a structured calendar proposal.
You receive only the proposal and its rationale. You do not know the original user
request, calendar, preference profile, or actual constraints. Never claim to have
verified any of those. Assess only what is supported by the proposal itself.

Score each dimension from 1 (very weak) to 5 (excellent):
- reasoning: whether the stated trade-off is justified by the information given;
- coherence: whether changes, claims and rejected alternatives agree internally;
- alternatives: whether plausible alternatives are considered and rejection explained;
- clarity: whether the proposal and rationale are clear and complete.

Return scores, specific weaknesses and actionable feedback. When evidence is
insufficient, explain the uncertainty rather than inventing calendar facts.
Answer only with JSON matching the schema."""


def build_critic_prompt(proposal: Proposal) -> str:
    """The caller cannot pass personal context to this function."""
    return "Assess this proposal and its rationale only:\n" + proposal.model_dump_json(indent=2)


def critique(proposal: Proposal, *, provider: Provider | None = None) -> CriticEvaluation:
    client = provider or get_provider(role="CRITIC")
    return client.generate_structured(build_critic_prompt(proposal), CriticEvaluation,
                                      system=SYSTEM)
