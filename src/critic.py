"""Independent Critic: final simulated calendar, operations and rationale only."""
from __future__ import annotations

import json
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from llm import LLMError, Provider, get_provider
from models import CurrentCriticEvaluation, Proposal
from scenario_v2 import V2Event

CRITIC_POLICY_VERSION = "plausibility_review_v1"


SYSTEM = """You are an independent quality-control reviewer of the resulting calendar.
You receive the exact final calendar produced by deterministic simulation, the
proposal with its rationale, and a limited technical validation report. You do
not receive the original request, full profile, original calendar, personal
preferences, or human labels. Do not claim to verify any of those. Validation
checks only the rules named in its report; it does not prove request satisfaction.

Assess whether the resulting schedule is humanly plausible, workable in daily
life, balanced against the visible activity load, and coherent with existing
events. Consider transitions, effort, rest, and trade-offs between productivity
and well-being. A mathematically free slot is not necessarily a good schedule.
Focus on proposed changes and their consequences; unchanged events provide
temporal context. Do not automatically blame the proposal for a pre-existing
problem. Distinguish in weaknesses and feedback:
- [objective]: a demonstrable contradiction or incompatible timing;
- [plausibility]: a concrete, consequential risk supported by visible events;
- [preference]: a subjective convenience improvement.
Give objective issues the greatest weight. A concrete, pertinent, evidence-based
question about practical schedule quality is enough to request re-evaluation by
the Proposer, even without proof of objective impossibility. Newly introduced
objective problems and relevant practical doubts should normally prompt review.
Minor, cosmetic or highly speculative observations should not. Do not request
revision merely because a different organization might be slightly nicer.

Never invent hard constraints: no universal transition buffer, commute, meal,
sleep or exercise rule. Consecutive events can be perfectly feasible, including
online meetings or small tasks in one place. If places or personal routines are
unknown, say so; do not infer a travel distance or declare a violation. A tight
transition between demanding activities may warrant a contextual question, not
a claim that a fixed buffer is required. Do not penalize
the absence of breaks without concrete context. Cite event IDs and times for
each material issue, distinguish observed facts from risks, and give actionable
feedback that leaves the final choice to the Proposer with full context.

Score each dimension from 1 (very weak) to 5 (excellent):
- reasoning: whether the trade-offs and practical schedule are justified by
  information available in the proposal and final calendar;
- coherence: whether changes, rationale and resulting calendar agree;
- alternatives: whether plausible alternatives are considered and explained;
- clarity: whether rationale and proposal are clear and complete.

Independently return plausibility_review with revision_required (boolean),
severity (none/low/moderate/high), reason and suggested_improvement. Severity
alone does not decide revision: a moderate observation may be recorded without
revision if it is too speculative or unlikely to matter. Request review when a
visible proposal-induced or aggravated scheduling concern is concrete and
relevant enough that checking it with the full context could improve the plan.
This is a request to re-evaluate, not an order to change calendar operations.
The Proposer may keep the same operations and give a grounded explanation.
If revision_required is true, cite event IDs/times, explain the practical
concern and uncertainty, and suggest what to examine without prescribing an
unsupported time or personal routine. Do not ask for review solely because
events are consecutive or a subjective preference differs from yours.

On revisions, prior_critic_reviews contains only your previous concerns and
proposal, not the user's hidden context. Compare them with the new operations
and rationale. Explicitly say whether the prior practical doubt is adequately
addressed or remains open, and why. A longer rationale or a repeated claim of
technical validity is not evidence of practical feasibility. If the Proposer
explains a constraint-based reason to keep the schedule, assess that explanation
on the available facts; do not demand an operation change just to comply with
your suggestion. Do not repeat an uncertain concern mechanically, but do not
invent a commute, meal, shower or other fact to close it. If essential personal
information is absent, state that limitation clearly.

Return the four scores, specific weaknesses, actionable feedback and the
explicit plausibility_review. Answer only with JSON matching the schema."""


def final_calendar_view(events: list[V2Event], proposal: Proposal, *,
                        original_ids: set[str], timezone: str) -> dict:
    """Serialize the simulated calendar without inventing added-event metadata.

    All simulated events are included; there is no token-based truncation.
    """
    zone = ZoneInfo(timezone)
    moved = {change.event_id for change in proposal.changes if change.type == "move"}
    rows = []
    for event in events:
        added = event.id not in original_ids
        rows.append({
            "id": event.id, "title": event.title,
            "start": event.start.astimezone(zone).isoformat(),
            "end": event.end.astimezone(zone).isoformat(),
            "category": None if added else event.category,
            "importance": None if added else event.importance,
            "fixed": None if added else event.fixed,
            "participants": None if added else event.participants,
            "description": None if added else event.description,
            "origin": "proposed_addition" if added else "existing",
            "change_status": "added" if added else "moved" if event.id in moved else "preserved",
        })
    return {"timezone": timezone, "coverage": "all_events_in_scenario_after_simulation",
            "events": rows,
            "metadata_note": ("Null metadata on added events means the Proposal contract did not "
                              "supply it; it is not a new personal preference or hard constraint.")}


def build_critic_prompt(proposal: Proposal, *, final_calendar: dict,
                        technical_validation: dict,
                        prior_reviews: list[dict] | None = None) -> str:
    """Only derived outcome, proposal and limited technical report enter the prompt."""
    packet: dict[str, object] = {
        "proposal": proposal.model_dump(mode="json"),
        "final_calendar": final_calendar,
        "technical_validation": technical_validation,
    }
    if prior_reviews:
        packet["prior_critic_reviews"] = prior_reviews
    return "Assess this structured proposal and its resulting calendar:\n" + json.dumps(
        packet, ensure_ascii=False, indent=2)


def critique(proposal: Proposal, *, final_calendar: dict, technical_validation: dict,
             prior_reviews: list[dict] | None = None,
             provider: Provider | None = None) -> CurrentCriticEvaluation:
    client = provider or get_provider(role="CRITIC")
    response = client.generate_structured(
        build_critic_prompt(proposal, final_calendar=final_calendar,
                            technical_validation=technical_validation,
                            prior_reviews=prior_reviews),
        CurrentCriticEvaluation, system=SYSTEM)
    try:
        return CurrentCriticEvaluation.model_validate(
            response.model_dump() if hasattr(response, "model_dump") else response)
    except (ValidationError, ValueError, TypeError):
        raise LLMError("Critic response missing or inconsistent plausibility review") from None
