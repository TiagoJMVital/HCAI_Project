"""Input adapter for the same structured Proposer output on v2 scenarios."""
from __future__ import annotations

from dataclasses import dataclass

from llm import Provider
from models import Proposal
from scenario_v2 import V2Scenario

SYSTEM_V2 = """You are a personal calendar assistant. Produce the same structured Proposal
JSON contract as the existing Proposer. Use only the supplied request, profile,
calendar and reference time. Do not move or delete fixed/protected events. Times
in proposed changes must include ISO 8601 timezone offsets consistent with the
profile timezone. Respect typed hard constraints and explain relevant trade-offs,
uncertainty and alternatives in the rationale. Autonomy preferences are user
preferences, not ACT/DEFER labels. Do not choose an autonomy label. Answer only
with JSON matching the supplied schema. Distinguish an event's modifiability
under known rules, a free calendar interval, and operational feasibility.
Flexible does not mean an external venue, person or resource is available at
every free time. Do not invent opening hours, travel times, or user routines.
When moving an existing event, weigh its disruption and any new external
dependency against the benefit for the request, and state material unknowns
in the rationale. A larger change may be justified; do not minimize changes
as a rigid rule."""

REVISION_GUIDANCE = (
    "Re-evaluate the scheduling concern using the original request, profile and calendar above. "
    "You may change the operations if a better feasible plan exists, or keep exactly the same "
    "operations with a rationale that directly addresses the concern. Do not change times merely "
    "to satisfy the reviewer. Explain uncertainty when personal details such as travel, meals or "
    "recovery are unknown; do not invent them. Repeating technical validity alone does not answer "
    "a practical-quality concern. Reassess the whole visible routine: cumulative effort, "
    "everyday needs, rest and whether reserved time can serve the user's objective. "
    "A small timing shift is not enough if the underlying concern remains. "
    "If changing operations, assess new risks, disruption, "
    "external dependencies and trade-offs introduced by the revision; do not assume the Critic's "
    "suggestion is an order. If keeping operations, provide grounds from the available context, "
    "not an unsupported assertion. Return the full structured proposal and rationale."
)


@dataclass(frozen=True)
class V2RuntimeScenario:
    """Minimal B pipeline bridge; the underlying v2 input remains unchanged."""
    source: V2Scenario

    @property
    def id(self): return self.source.scenario_id

    @property
    def family(self): return self.source.family_id

    @property
    def category(self): return "v2"

    @property
    def calendar(self): return self.source.calendar.events

    @property
    def user_request(self): return self.source.user_request

    @property
    def now(self): return self.source.now.isoformat()


def propose_v2(profile, scenario: V2RuntimeScenario, *, provider: Provider,
               previous: Proposal | None = None, feedback: str | None = None) -> Proposal:
    source = scenario.source
    prompt = (f"Reference time: {source.now.isoformat()}\n"
              f"User request: {source.user_request}\n"
              f"Profile: {source.profile.model_dump_json()}\n"
              f"Original calendar: {source.calendar.model_dump_json()}")
    if previous is not None and feedback is not None:
        prompt += (f"\nPrevious proposal: {previous.model_dump_json()}\n"
                   f"Reviewer feedback: {feedback}\n"
                   f"{REVISION_GUIDANCE}")
    return provider.generate_structured(prompt, Proposal, system=SYSTEM_V2)
