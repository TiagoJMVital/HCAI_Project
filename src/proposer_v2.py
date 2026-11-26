"""Input adapter for the same structured Proposer output on v2 scenarios."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from llm import Provider, prompt_json_schema
from models import (PROPOSER_WIRE_SCHEMA_VERSION, Proposal,
                    ProposerWireProposal)
from scenario_v2 import V2Scenario

SYSTEM_V2 = """You are a personal calendar assistant. Produce the compact structured
proposal JSON contract supplied below. Use only the supplied request, profile,
calendar and reference time. Do not move or delete fixed/protected events unless
an exact externally confirmed exception is supplied for that event and operation. Times
in proposed changes must include ISO 8601 timezone offsets consistent with the
profile timezone. Respect typed hard constraints and explain relevant trade-offs,
uncertainty and alternatives in the rationale. Autonomy preferences are user
preferences, not ACT/DEFER labels. Do not choose an autonomy label. Answer only
with JSON matching the supplied schema. Distinguish an event's modifiability
under known rules, a free calendar interval, and operational feasibility.
Omit optional fields that do not apply or are unknown; do not emit them as null.
Flexible does not mean an external venue, person or resource is available at
every free time. Do not invent opening hours, travel times, or user routines.
When moving an existing event, weigh its disruption and any new external
dependency against the benefit for the request, and state material unknowns
in the rationale. A larger change may be justified; do not minimize changes
as a rigid rule. For added activities, supply category, importance and
participants only when supported by the request or profile. A declared
category may be used by typed duration checks; never label an unknown activity
as work or thesis merely to satisfy a numeric target. An empty changes list
requires a concrete explanation of why the current calendar already answers
the request; do not use it to skip a difficult request. Keep the rationale
concise: use one short sentence per material constraint or priority, include
only materially distinct alternatives, and give each rejection in one short
sentence. State every material uncertainty, but state it once. Do not repeat
event descriptions, timestamps or change details already present in `changes`.
Keep `summary` focused on the selected plan and its main trade-off."""

PROPOSER_WIRE_SCHEMA_SHA256 = hashlib.sha256(json.dumps(
    prompt_json_schema(ProposerWireProposal), ensure_ascii=False,
    sort_keys=True, separators=(",", ":"),
).encode()).hexdigest()

REVISION_GUIDANCE = (
    "Re-evaluate the scheduling concern using the original request, profile and calendar above. "
    "Change operations only if a better feasible plan exists; you may keep exactly the same operations "
    "if the rationale directly addresses the concern. A small timing shift is not enough if the "
    "underlying concern remains. Do not shift times merely to satisfy the reviewer, and do not invent travel, "
    "meal, recovery or availability facts. Reassess cumulative effort, everyday needs, rest, "
    "external dependencies and disruption. Repeating technical validity alone does not resolve a practical "
    "concern. Return the full proposal, but keep each rationale item brief, state each material "
    "uncertainty once, and do not repeat details already encoded in `changes`."
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
    if source.aggregate_requirements:
        prompt += ("\nTyped duration requirements (checked on the final calendar; "
                   "scheduled time is not proof of completed work): "
                   + json.dumps([item.model_dump(mode="json") for item in source.aggregate_requirements]))
    if source.confirmed_changes:
        prompt += ("\nOnly these exact externally confirmed exceptions may change "
                   "otherwise protected events; they do not authorize unrelated changes: "
                   + json.dumps([item.model_dump(mode="json") for item in source.confirmed_changes]))
    if previous is not None and feedback is not None:
        previous_format = PROPOSER_WIRE_SCHEMA_VERSION
        try:
            compact_previous = ProposerWireProposal.from_proposal(previous).model_dump_json(
                exclude_none=True, by_alias=True)
        except ValueError:
            # A manually replayed historical proposal may predate compact_v1
            # and exceed its prose bounds. Preserve all prior evidence rather
            # than truncating it; only newly generated output uses the wire schema.
            compact_previous = previous.model_dump_json(exclude_none=True)
            previous_format = "canonical_historical"
        prompt += (f"\nPrevious proposal ({previous_format}): {compact_previous}\n"
                   f"Reviewer feedback: {feedback}\n"
                   f"{REVISION_GUIDANCE}")
    wire = provider.generate_structured(prompt, ProposerWireProposal, system=SYSTEM_V2)
    return wire.to_proposal()
