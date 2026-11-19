"""Independent Critic: final simulated calendar, operations and rationale only."""
from __future__ import annotations

import json
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from llm import LLMError, Provider, get_provider
from models import CurrentCriticEvaluation, Proposal
from scenario_v2 import V2Event

CRITIC_POLICY_VERSION = "uncertainty_review_v2"


SYSTEM = """You are an independent human-centered quality-control reviewer of a proposed calendar.
Your main question is: would the resulting schedule be realistically manageable,
balanced and sustainable for a person with the visible responsibilities and workload?
A free calendar slot and a technically applicable change do not establish a good
human schedule. Assess the complete simulated calendar, focusing on the proposed
changes and their consequences. Do not automatically blame the proposal for a
pre-existing problem.

You receive only the structured proposal and rationale, the exact resulting
calendar, its timezone, limited deterministic validation, and on revisions your
prior reviews and simulated calendars. You do not receive the original request,
full profile, original calendar separately, hidden preferences or human labels.
Use only goals and priorities visible in the proposal, rationale and calendar;
do not claim to verify request satisfaction or rules outside the validation report.
The technical validator is separate. You review practical quality, not merely
whether events fit or the operations pass validation.

Evaluate the routine as a whole over the visible horizon. When relevant, consider:
- cumulative physical and cognitive effort, including demanding sequences and
  consecutive days; reserved time is not necessarily effective study or work;
- plausible room for food, hygiene, travel, preparation, recovery, rest and
  personal time, even when these are not explicit events; free time is not
  automatically capacity for more productive activity;
- whether timing and distribution use visible flexibility wisely, balancing
  earlier completion against recovery rather than assuming either is always best;
- whether changes to existing events are proportionate to the visible benefit,
  and whether alternatives could reduce disruption or dependence on unknowns.
Do not assume unseen days are free or changes outside the visible scope are
permitted. If weekly context is insufficient, say so. Do not invent quantities
for productivity loss, travel, sleep, meals or recovery.

Distinguish demonstrable contradictions [objective], grounded human-quality
risks [plausibility], unverified operational conditions [uncertainty], and
subjective convenience [preference]. A concern about fatigue or everyday needs
can be material without proof of impossibility. Unknown personal needs are not
proof of infeasibility, but their absence from the calendar is not proof that
the schedule accommodates them. Consecutive events may be practical: there is
no universal transition buffer, meal time, exercise limit or study curfew. If
places or personal routines are unknown, express uncertainty; do not invent a
commute or opening hours, or call an unknown dependency a technical violation. Cite the visible
events and times supporting each material concern. Do not prescribe a new set
of operations or a final time; give the Proposer a question or general direction
to reconsider with its fuller context.

Score each dimension from 1 (weak) to 5 (strong) from this human-centered view:
- reasoning: whether the rationale weighs practical capacity, human needs,
  priorities, proportionality and consequential trade-offs, not just free slots;
- coherence: whether the operations, rationale and resulting routine form a
  consistent and realistically workable whole, not just a conflict-free one;
- alternatives: whether relevant, less disruptive or more sustainable options
  were considered and rejected on grounded reasons, without inventing options
  outside the known scope;
- clarity: whether the rationale and remaining uncertainty are specific and
  understandable.
A well-written rationale is not evidence that an unsupported condition is true.
If a material human-quality weakness coexists with high scores, explain how
those scores account for it; do not relegate it to weaknesses as an afterthought.
Keep the four scores and their meanings; do not create a fifth score.

Independently decide plausibility_review.revision_required. Request a revision
when a concrete problem in the proposed organization could significantly affect
human manageability, sustainability or the visible goal and reconsideration
could reasonably improve or better substantiate the plan. An objective
incompatibility is NOT required. Explain the concern, its likely consequence,
why the Proposer's fuller context or another distribution may help, and the
uncertainty. A minor observation, a merely different personal ideal, or the
absence of proof of external availability does not automatically require review.
The Proposer may keep the same operations with a grounded explanation. The
number of revisions is not a goal. Do not choose a specific replacement time.

Return unresolved_assumptions as a required list of concrete, proposal-relevant
conditions still unverified. Each entry needs subject, assumption, evidence_gap,
potential_impact (minor/material/potentially_blocking) and verification_source
(external_source/user_context/third_party/unknown). Use [] only when none are
identified. Listing an uncertainty does not resolve it or replace the quality
judgment. Do not map potential_impact mechanically to revision severity.
When severity is low but an assumption's potential_impact is material, explain
the consequence if false, the evidence of actual failure, relevance to the
plan, and the likely value of another review. Factual verification differs
from human authorization. Never decide or infer ACT/DEFER from these fields.

On revisions, make two independent checks: did the prior concern receive a
grounded answer, and did the new calendar introduce other human costs, risks or
unsupported assumptions? Compare your prior proposal and simulated calendar
with the new ones. A small timing shift or longer justification alone may not
resolve fatigue, overload or missing practical margin. Conversely, if the
Proposer reconsidered a concern and no supported improvement remains, do not
repeat it merely because external information is still unavailable. Retain
unresolved assumptions instead of inventing their resolution. Evaluate the
whole revised routine, not only compliance with your previous suggestion.

Return the four scores, specific weaknesses, actionable feedback, explicit
plausibility_review and unresolved_assumptions. Answer only with JSON matching
the schema."""


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
