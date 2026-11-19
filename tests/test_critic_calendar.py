"""Outcome-aware Critic contract tests; no provider or calendar writes."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from calendar_v2 import simulate
from critic import SYSTEM, final_calendar_view
from models import Change, CurrentCriticEvaluation, CriticScores, PlausibilityReview, Proposal, Rationale
from pipeline_b import CriticSettings, run_config_b
from proposer_v2 import V2RuntimeScenario, propose_v2
from scenario_v2 import V2Scenario, load_scenario


class ScriptedProvider:
    name = "mock"
    model = "scripted"

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def generation_config(self):
        return {"mock": True}

    def generate_structured(self, prompt, schema, *, system=""):
        self.calls.append((prompt, schema, system))
        return self.answers.pop(0)


def scenario():
    return load_scenario(ROOT / "data/scenarios/working_student_deadline_001.json")


def add_study(start="2026-11-09T20:00:00+00:00"):
    return Proposal(changes=[Change(type="add", event_id="study_new", title="Assessment preparation",
                                    to_start=start, to_end="2026-11-09T21:30:00+00:00")],
                    rationale=Rationale(constraints=["keep work fixed"], priorities=["study"],
                                        alternatives_considered=[], summary="Study after the gym."))


def score(value, feedback="No material issue"):
    return CurrentCriticEvaluation(scores=CriticScores(reasoning=value, coherence=value,
                                               alternatives=value, clarity=value),
                            weaknesses=[] if value >= 4 else ["[plausibility] gym_mon ends when study_new begins"],
                            feedback=feedback, plausibility_review=PlausibilityReview(
                                revision_required=False, severity="none", reason="", suggested_improvement=""),
                            unresolved_assumptions=[])


def run(source, proposals, evaluations, settings=None):
    proposer = ScriptedProvider(proposals)
    critic = ScriptedProvider(evaluations)
    record = run_config_b(source.profile, V2RuntimeScenario(source),
                          proposer_provider=proposer, critic_provider=critic,
                          settings=settings, proposer_fn=propose_v2,
                          simulate_fn=lambda proposal: simulate(source, proposal))
    return record, proposer, critic


def packet(call):
    return json.loads(call[0].split("\n", 1)[1])


def test_full_exact_outcome_and_unmodified_neighbors():
    source = scenario()
    proposal = add_study()
    after, validation = simulate(source, proposal)
    record, _, critic = run(source, [proposal], [score(4)])
    sent = packet(critic.calls[0])
    view = sent["final_calendar"]
    assert sent["technical_validation"] == validation
    assert view == final_calendar_view(after, proposal,
                                       original_ids={event.id for event in source.calendar.events},
                                       timezone=source.profile.timezone)
    assert len(view["events"]) == len(source.calendar.events) + 1
    assert {event["id"] for event in view["events"]} == {
        event.id for event in source.calendar.events} | {"study_new"}
    assert next(event for event in view["events"] if event["id"] == "gym_mon")["end"] == \
        next(event for event in view["events"] if event["id"] == "study_new")["start"]
    assert next(event for event in view["events"] if event["id"] == "work_tue")["change_status"] == "preserved"
    assert record["iterations"][0]["result_calendar"] == view
    assert record["final_result_calendar"] == view
    assert proposal.model_dump(mode="json") == sent["proposal"]


def test_added_metadata_unknown_and_private_context_absent():
    source = scenario()
    source.profile.description = "PRIVATE_PROFILE_MARKER"
    source.user_request = "PRIVATE_REQUEST_MARKER"
    source.profile.soft_preferences[0].description = "PRIVATE_PREFERENCE_MARKER"
    record, proposer, critic = run(source, [add_study()], [score(4)])
    prompt, _, system = critic.calls[0]
    for secret_context in ("PRIVATE_PROFILE_MARKER", "PRIVATE_REQUEST_MARKER", "PRIVATE_PREFERENCE_MARKER"):
        assert secret_context not in prompt + system
    added = next(event for event in packet(critic.calls[0])["final_calendar"]["events"]
                 if event["id"] == "study_new")
    assert added["origin"] == "proposed_addition"
    assert all(added[key] is None for key in ("category", "importance", "fixed", "participants", "description"))
    assert "PRIVATE_REQUEST_MARKER" in proposer.calls[0][0]
    assert record["status"] == "proposal_ready"


def test_consecutive_events_are_not_automatically_rejected():
    source = scenario()
    # The mocked acceptance tests pipeline neutrality, not LLM semantic quality.
    record, _, critic = run(source, [add_study()], [score(4)])
    assert record["status"] == "proposal_ready"
    assert record["iterations"][0]["validation"]["violations"] == []
    assert "no universal transition buffer" in SYSTEM
    assert "places or personal routines are" in SYSTEM
    assert critic.calls[0][1] is CurrentCriticEvaluation


@pytest.mark.parametrize("existing_title,new_title,existing_description", [
    ("Study at home", "Hang laundry at home", "Private activity at home."),
    ("Online meeting", "Online follow-up", "Remote meeting."),
])
def test_compatible_back_to_back_events_do_not_trigger_universal_buffer(
        existing_title, new_title, existing_description):
    raw = scenario().model_dump(mode="json")
    raw["calendar"]["events"].append({
        "id": "compatible_first", "title": existing_title,
        "start": "2026-11-12T19:00:00+00:00", "end": "2026-11-12T20:00:00+00:00",
        "category": "personal", "importance": 2, "fixed": False,
        "participants": ["user"], "description": existing_description,
    })
    source = V2Scenario.model_validate(raw)
    candidate = Proposal(changes=[Change(type="add", event_id="compatible_second", title=new_title,
                                         to_start="2026-11-12T20:00:00+00:00",
                                         to_end="2026-11-12T20:15:00+00:00")],
                         rationale=Rationale(constraints=[], priorities=["keep a compact same-location sequence"],
                                             alternatives_considered=[],
                                             summary="The activities are both at home or online; no travel is indicated."))
    result, _, critic = run(source, [candidate], [score(4)])
    assert result["status"] == "proposal_ready"
    assert result["iterations"][0]["validation"]["violations"] == []
    events = packet(critic.calls[0])["final_calendar"]["events"]
    first = next(event for event in events if event["id"] == "compatible_first")
    second = next(event for event in events if event["id"] == "compatible_second")
    assert first["end"] == second["start"]


def test_human_workload_review_can_continue_after_cosmetic_revision():
    source = scenario()
    first = add_study()
    slight_shift = add_study("2026-11-09T20:15:00+00:00")
    reconsidered = Proposal(
        changes=[Change(type="add", event_id="study_new", title="Assessment preparation",
                        to_start="2026-11-09T20:45:00+00:00",
                        to_end="2026-11-09T22:15:00+00:00")],
        rationale=Rationale(constraints=["keep work fixed"], priorities=["study"],
                            alternatives_considered=[],
                            summary="Preserve the full block with more transition time, while noting the later finish."))
    concern = CurrentCriticEvaluation(
        scores=CriticScores(reasoning=2, coherence=3, alternatives=4, clarity=4),
        weaknesses=["[plausibility] The proposed activity follows a long sequence of work and exercise."],
        feedback="Reassess whether the schedule leaves practical room for recovery and focused work.",
        plausibility_review=PlausibilityReview(
            revision_required=True, severity="moderate",
            reason="The technically valid added block may be hard to use effectively after the visible workload.",
            suggested_improvement="Reconsider the whole evening and the distribution of effort."),
        unresolved_assumptions=[])
    still_open = concern.model_copy(deep=True)
    still_open.plausibility_review.reason = (
        "A small shift does not establish that practical recovery or effective focus is possible.")
    accepted = score(4, "The revised routine is sufficiently supported in the visible context.")
    # These scripted judgments exercise the cycle; they do not establish real scheduling quality.
    record, proposer, critic = run(source, [first, slight_shift, reconsidered],
                                   [concern, still_open, accepted], CriticSettings(max_refinements=2))
    assert all(step["validation"]["valid"] for step in record["iterations"])
    assert [step["acceptance_policy"]["accepted"] for step in record["iterations"]] == [False, False, True]
    assert record["status"] == "proposal_ready" and record["refinements"] == 2
    assert "practical room for recovery" in proposer.calls[1][0]
    assert "A small timing shift is not enough" in proposer.calls[1][0]
    assert "small shift does not establish" in proposer.calls[2][0]
    assert "human-centered" in critic.calls[0][2]
    assert "realistically workable whole" in critic.calls[0][2]


def test_critic_contract_cannot_return_calendar_operations():
    assert "changes" not in CurrentCriticEvaluation.model_fields
    assert "to_start" not in CurrentCriticEvaluation.model_fields
    assert "unresolved_assumptions" in CurrentCriticEvaluation.model_fields
    assert "Do not prescribe a new set" in SYSTEM


def test_contextual_risk_feedback_rebuilds_outcome_on_revision():
    source = scenario()
    first = add_study()
    revised = add_study("2026-11-09T21:00:00+00:00")
    record, proposer, critic = run(source, [first, revised], [
        score(3, "study_new starts immediately after gym_mon; consider later start if constraints permit"),
        score(5)], CriticSettings(max_refinements=1))
    assert record["status"] == "proposal_ready" and record["refinements"] == 1
    first_calendar = packet(critic.calls[0])["final_calendar"]
    revised_calendar = packet(critic.calls[1])["final_calendar"]
    assert next(e for e in first_calendar["events"] if e["id"] == "study_new")["start"].endswith("20:00:00+00:00")
    assert next(e for e in revised_calendar["events"] if e["id"] == "study_new")["start"].endswith("21:00:00+00:00")
    assert record["iterations"][0]["result_calendar"] == first_calendar
    assert record["iterations"][1]["result_calendar"] == revised_calendar
    assert "consider later start" in proposer.calls[1][0]
    assert record["iterations"][1]["proposer_feedback"]


def test_preexisting_overlap_is_visible_but_not_attributed_automatically():
    raw = scenario().model_dump(mode="json")
    raw["calendar"]["events"][1]["start"] = raw["calendar"]["events"][0]["start"]
    raw["calendar"]["events"][1]["end"] = raw["calendar"]["events"][0]["end"]
    source = V2Scenario.model_validate(raw)
    record, _, critic = run(source, [add_study()], [score(4)])
    assert record["status"] == "proposal_ready"
    events = packet(critic.calls[0])["final_calendar"]["events"]
    assert next(e for e in events if e["id"] == "work_mon")["change_status"] == "preserved"
    assert next(e for e in events if e["id"] == "work_tue")["change_status"] == "preserved"
    assert "Do not automatically blame the proposal" in SYSTEM


def test_unresolved_critic_issue_and_revision_limit():
    source = scenario()
    record, proposer, critic = run(source, [add_study()] * 2, [score(3)] * 2,
                                   CriticSettings(max_refinements=1))
    assert record["status"] == "deferred_critic_threshold"
    assert record["refinements"] == 1
    assert record["unresolved_critic_weaknesses"] == score(3).weaknesses
    assert len(proposer.calls) == len(critic.calls) == 2
    assert all(step["result_calendar"] for step in record["iterations"])
