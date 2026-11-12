"""Configuração B: Proposer, validação, Critic e regras fixas de autonomia."""
from __future__ import annotations

from dataclasses import dataclass

from calendar_ops import find_violations
from critic import critique
from llm import LLMError, Provider
from models import CriticEvaluation, Profile, Proposal, Scenario
from proposer import propose
from rules import rule_based_decision


@dataclass(frozen=True)
class CriticSettings:
    threshold: float = 4.0
    max_refinements: int = 3
    min_dimension_score: int = 1

    def __post_init__(self):
        if not 1 <= self.threshold <= 5:
            raise ValueError("critic threshold deve estar entre 1 e 5")
        if not 0 <= self.max_refinements <= 10:
            raise ValueError("max_refinements deve estar entre 0 e 10")
        if not 1 <= self.min_dimension_score <= 5:
            raise ValueError("min_dimension_score deve estar entre 1 e 5")


def _accepted(evaluation: CriticEvaluation, settings: CriticSettings) -> bool:
    scores = evaluation.scores
    return evaluation.overall >= settings.threshold and min(
        scores.reasoning, scores.coherence, scores.alternatives, scores.clarity
    ) >= settings.min_dimension_score


def _review_feedback(evaluation: CriticEvaluation) -> str:
    return (f"Critic scores: {evaluation.scores.model_dump_json()}. "
            f"Weaknesses: {evaluation.weaknesses}. "
            f"Actionable feedback: {evaluation.feedback}")


def run_config_b(profile: Profile, scenario: Scenario, *, proposer_provider: Provider,
                 critic_provider: Provider, settings: CriticSettings | None = None) -> dict:
    """Uma proposta inicial e até `max_refinements` revisões, sem escrita externa."""
    settings = settings or CriticSettings()
    record = {
        "configuration": "B", "scenario_id": scenario.id, "family": scenario.family,
        "category": scenario.category,
        "proposer_provider": proposer_provider.name, "proposer_model": proposer_provider.model,
        "proposer_generation_config": proposer_provider.generation_config(),
        "critic_provider": critic_provider.name, "critic_model": critic_provider.model,
        "critic_generation_config": critic_provider.generation_config(),
        "critic_settings": {"threshold": settings.threshold,
                            "max_refinements": settings.max_refinements,
                            "min_dimension_score": settings.min_dimension_score},
        "iterations": [], "initial_proposal": None, "final_proposal": None,
        "final_score": None, "refinements": 0, "critic_accepted": False,
        "decision": None, "reasons": [], "status": "running",
    }
    previous: Proposal | None = None
    feedback: str | None = None

    for revision in range(settings.max_refinements + 1):
        item = {"index": revision, "proposer_feedback": feedback,
                "proposal": None, "validation": None, "critic_evaluation": None}
        record["iterations"].append(item)
        try:
            proposal = propose(profile, scenario, provider=proposer_provider,
                               previous=previous, feedback=feedback)
        except LLMError as exc:
            record.update(status="proposer_error", error=str(exc),
                          error_stage="proposer", safe_action="no_autonomous_action")
            return record

        item["proposal"] = proposal.model_dump()
        if revision == 0:
            record["initial_proposal"] = item["proposal"]
        record["final_proposal"] = item["proposal"]
        record["refinements"] = revision
        previous = proposal
        try:
            violations = find_violations(scenario.calendar, proposal, profile)
        except Exception:  # a falha do validador nunca autoriza uma ação
            record.update(status="validation_error", error="falha da validação determinística",
                          error_stage="validation", safe_action="no_autonomous_action")
            return record
        item["validation"] = {"structural": "valid", "violations": violations}

        if violations:
            feedback = ("Deterministic validation found these operational problems: "
                        + "; ".join(violations)
                        + ". Revise the changes before any Critic assessment.")
            if revision == settings.max_refinements:
                record.update(status="deferred_invalid_proposal", decision="defer",
                              reasons=["validação determinística falhou"] + violations)
                return record
            continue

        try:
            evaluation = critique(proposal, provider=critic_provider)
        except LLMError as exc:
            record.update(status="critic_error", error=str(exc),
                          error_stage="critic", safe_action="no_autonomous_action")
            return record

        item["critic_evaluation"] = evaluation.model_dump() | {"overall": evaluation.overall}
        record["final_score"] = evaluation.overall
        if _accepted(evaluation, settings):
            decision, reasons = rule_based_decision(proposal, scenario.calendar, violations)
            record.update(status="proposal_ready", critic_accepted=True,
                          decision=decision, reasons=reasons or ["regras fixas permitem act"])
            return record

        feedback = _review_feedback(evaluation)
        if revision == settings.max_refinements:
            record.update(status="deferred_critic_threshold", decision="defer",
                          reasons=["Critic não atingiu os critérios de aceitação"])
            return record

    raise AssertionError("limite do ciclo de revisão ultrapassado")
