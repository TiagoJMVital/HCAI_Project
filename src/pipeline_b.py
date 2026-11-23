"""Configuração B: Proposer, validação, Critic e regras fixas de autonomia."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from critic import CRITIC_POLICY_VERSION, RESULT_CALENDAR_VERSION, critique, final_calendar_view
from llm import LLMError, Provider, RateLimitError
from models import CurrentCriticEvaluation, Proposal
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


def _numeric_passed(evaluation: CurrentCriticEvaluation, settings: CriticSettings) -> bool:
    scores = evaluation.scores
    return evaluation.overall >= settings.threshold and min(
        scores.reasoning, scores.coherence, scores.alternatives, scores.clarity
    ) >= settings.min_dimension_score


def _review_feedback(evaluation: CurrentCriticEvaluation, *, numeric_passed: bool) -> str:
    parts = []
    if not numeric_passed:
        parts.append(f"Numeric Critic criteria failed. Scores: {evaluation.scores.model_dump_json()}.")
    if evaluation.plausibility_review.revision_required:
        review = evaluation.plausibility_review
        parts.append(f"Plausibility revision required ({review.severity}): {review.reason} "
                     f"Suggested direction: {review.suggested_improvement} "
                     "The Critic lacks the full user constraints; explain if no better feasible option exists.")
    if evaluation.unresolved_assumptions:
        parts.append("Unverified conditions to reassess: " +
                     str([entry.model_dump() for entry in evaluation.unresolved_assumptions]))
    parts.append(f"Weaknesses: {evaluation.weaknesses}. Actionable feedback: {evaluation.feedback}")
    return " ".join(parts)


def run_config_b(profile, scenario, *, proposer_provider: Provider,
                 critic_provider: Provider, settings: CriticSettings | None = None,
                 proposer_fn: Callable,
                 simulate_fn: Callable,
                 initial_proposal: Proposal | None = None) -> dict:
    """Uma proposta inicial e até `max_refinements` revisões, sem escrita externa."""
    settings = settings or CriticSettings()
    if initial_proposal is not None:
        initial_proposal = Proposal.model_validate(initial_proposal)
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
        "critic_input_version": "final_calendar_v1",
        "critic_policy_version": CRITIC_POLICY_VERSION,
        "result_calendar_version": RESULT_CALENDAR_VERSION,
        "final_result_calendar": None,
        "final_unresolved_assumptions": None,
        "uncertainty_history": [],
    }
    previous: Proposal | None = None
    feedback: str | None = None
    prior_reviews: list[dict] = []

    for revision in range(settings.max_refinements + 1):
        item = {"index": revision, "proposer_feedback": feedback,
                "proposer_source": "replayed" if revision == 0 and initial_proposal is not None else "generated",
                "proposal": None, "validation": None, "result_calendar": None,
                "critic_evaluation": None, "acceptance_policy": None,
                "operations_changed_from_previous": None,
                "rationale_changed_from_previous": None,
                "prior_critic_reviews": list(prior_reviews)}
        record["iterations"].append(item)
        try:
            proposal = (initial_proposal if revision == 0 and initial_proposal is not None else
                        proposer_fn(profile, scenario, provider=proposer_provider,
                                    previous=previous, feedback=feedback))
            if getattr(proposer_provider, "last_failed_outputs", None):
                item["recovered_proposer_outputs"] = proposer_provider.last_failed_outputs
            if getattr(proposer_provider, "last_rate_limit_attempts", None):
                item["recovered_proposer_rate_limit_attempts"] = proposer_provider.last_rate_limit_attempts
        except LLMError as exc:
            record.update(status="proposer_error", error=str(exc),
                          error_stage="proposer", safe_action="no_autonomous_action")
            if exc.failed_outputs:
                record["failed_llm_outputs"] = exc.failed_outputs
            if exc.diagnostics:
                record["llm_diagnostics"] = exc.diagnostics
                if isinstance(exc, RateLimitError):
                    record["rate_limit_diagnostics"] = exc.diagnostics
            return record

        item["proposal"] = proposal.model_dump()
        if previous is not None:
            item["operations_changed_from_previous"] = proposal.changes != previous.changes
            item["rationale_changed_from_previous"] = proposal.rationale != previous.rationale
        if revision == 0:
            record["initial_proposal"] = item["proposal"]
        record["final_proposal"] = item["proposal"]
        record["final_result_calendar"] = None
        record["final_unresolved_assumptions"] = None
        record["refinements"] = revision
        previous = proposal
        try:
            result_events, validation = simulate_fn(proposal)
            violations = validation["violations"]
            if not isinstance(violations, list) or validation["valid"] != (not violations):
                raise ValueError("inconsistent deterministic validation report")
        except Exception:  # a falha do validador nunca autoriza uma ação
            record.update(status="validation_error", error="falha da validação determinística",
                          error_stage="validation", safe_action="no_autonomous_action")
            return record
        item["validation"] = validation

        if violations:
            feedback = ("Deterministic validation found these operational problems: "
                        + "; ".join(violations)
                        + ". Revise the changes before any Critic assessment.")
            if revision == settings.max_refinements:
                record.update(status="deferred_invalid_proposal", decision="defer",
                              reasons=["validação determinística falhou"] + violations)
                return record
            continue

        if result_events is None:
            record.update(status="validation_error", error="simulação sem calendário final",
                          error_stage="validation", safe_action="no_autonomous_action")
            return record

        try:
            result_calendar = final_calendar_view(
                result_events, proposal,
                original_ids={event.id for event in scenario.calendar},
                timezone=profile.timezone, version=RESULT_CALENDAR_VERSION)
        except Exception:
            record.update(status="validation_error", error="falha na serialização do calendário final",
                          error_stage="validation", safe_action="no_autonomous_action")
            return record
        item["result_calendar"] = result_calendar
        record["final_result_calendar"] = result_calendar

        try:
            evaluation = critique(proposal, final_calendar=result_calendar,
                                  technical_validation=validation,
                                  prior_reviews=prior_reviews, provider=critic_provider)
            if getattr(critic_provider, "last_failed_outputs", None):
                item["recovered_critic_outputs"] = critic_provider.last_failed_outputs
            if getattr(critic_provider, "last_rate_limit_attempts", None):
                item["recovered_critic_rate_limit_attempts"] = critic_provider.last_rate_limit_attempts
        except LLMError as exc:
            record.update(status="critic_error", error=str(exc),
                          error_stage="critic", safe_action="no_autonomous_action")
            if exc.failed_outputs:
                record["failed_llm_outputs"] = exc.failed_outputs
            if exc.diagnostics:
                record["llm_diagnostics"] = exc.diagnostics
                if isinstance(exc, RateLimitError):
                    record["rate_limit_diagnostics"] = exc.diagnostics
            return record

        item["critic_evaluation"] = evaluation.model_dump() | {"overall": evaluation.overall}
        assumptions = [entry.model_dump() for entry in evaluation.unresolved_assumptions]
        item["unresolved_assumptions"] = assumptions
        record["final_unresolved_assumptions"] = assumptions
        record["uncertainty_history"].append({"iteration": revision, "unresolved_assumptions": assumptions})
        record["final_score"] = evaluation.overall
        numeric_passed = _numeric_passed(evaluation, settings)
        plausibility_revision_required = evaluation.plausibility_review.revision_required
        revision_causes = (["numeric_criteria_failed"] if not numeric_passed else []) + (
            ["plausibility_revision_required"] if plausibility_revision_required else [])
        item["acceptance_policy"] = {
            "numeric_criteria_passed": numeric_passed,
            "plausibility_revision_required": plausibility_revision_required,
            "accepted": not revision_causes,
            "revision_causes": revision_causes,
        }
        if not revision_causes:
            decision, reasons = rule_based_decision(proposal, scenario.calendar, violations)
            record.update(status="proposal_ready", critic_accepted=True,
                          decision=decision, reasons=reasons or ["regras fixas permitem act"])
            return record

        prior_reviews.append({
            "iteration": revision,
            "proposal": proposal.model_dump(mode="json"),
            "result_calendar": result_calendar,
            "plausibility_review": evaluation.plausibility_review.model_dump(),
            "unresolved_assumptions": assumptions,
            "weaknesses": evaluation.weaknesses,
            "feedback": evaluation.feedback,
        })
        feedback = _review_feedback(evaluation, numeric_passed=numeric_passed)
        if revision == settings.max_refinements:
            record.update(status="deferred_critic_threshold", decision="defer",
                          reasons=revision_causes,
                          unresolved_critic_weaknesses=evaluation.weaknesses,
                          unresolved_plausibility_review=(evaluation.plausibility_review.model_dump()
                              if plausibility_revision_required else None))
            return record

    raise AssertionError("limite do ciclo de revisão ultrapassado")
