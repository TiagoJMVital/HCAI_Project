"""Explicit Critic revision decisions; all model responses are scripted."""
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))

from benchmark_v2 import import_scenario
from calendar_v2 import simulate
from critic import CRITIC_POLICY_VERSION, critique
from llm import LLMError
from models import (Change, CriticEvaluation, CriticScores, CurrentCriticEvaluation,
                    PlausibilityReview, Proposal, Rationale)
from pipeline_b import run_config_b
from proposer_v2 import V2RuntimeScenario, propose_v2
from run_config_a_v2 import run_one as run_a
from run_config_b_v2 import run_one as run_b
from proposal_catalog_v2 import import_result
from scenario_v2 import load_scenario


class ScriptedProvider:
    name = "mock"
    model = "mock-gpt"

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def generation_config(self):
        return {"mock": True}

    def generate_structured(self, prompt, schema, *, system=""):
        self.calls.append((prompt, schema, system))
        return self.answers.pop(0)


def candidate(start="2026-11-09T20:15:00+00:00"):
    return Proposal(changes=[Change(type="add", title="Assessment preparation",
                                    to_start=start, to_end="2026-11-09T21:45:00+00:00")],
                    rationale=Rationale(constraints=["work fixed"], priorities=["study"],
                                        alternatives_considered=[], summary="Study after gym."))


def review(required=False, severity="none", reason="", suggestion=""):
    return PlausibilityReview(revision_required=required, severity=severity,
                              reason=reason, suggested_improvement=suggestion)


def evaluated(scores=(4, 5, 4, 4), plausibility=None):
    return CurrentCriticEvaluation(
        scores=CriticScores(reasoning=scores[0], coherence=scores[1],
                            alternatives=scores[2], clarity=scores[3]),
        weaknesses=["[plausibility] new_0 follows gym_mon"] if plausibility and plausibility.reason else [],
        feedback="Review the transition only if the user's constraints permit it.",
        plausibility_review=plausibility or review())


@pytest.fixture
def context(tmp_path):
    path = import_scenario(tmp_path, ROOT.parent / "scenario_v2_example.json", "train")
    return tmp_path, load_scenario(path)


def run(context, proposals, evaluations):
    _, source = context
    proposer, critic = ScriptedProvider(proposals), ScriptedProvider(evaluations)
    result = run_config_b(source.profile, V2RuntimeScenario(source),
                          proposer_provider=proposer, critic_provider=critic,
                          proposer_fn=propose_v2,
                          simulate_fn=lambda proposal: simulate(source, proposal))
    return result, proposer, critic


def test_score_425_with_required_revision_reaches_proposer(context):
    risk = review(True, "moderate",
                  "new_0 starts 20:15 after gym_mon ends 20:00 following work_mon; fatigue may reduce study quality",
                  "Explore more transition time if the user's constraints permit it")
    result, proposer, critic = run(context, [candidate(), candidate("2026-11-09T21:00:00+00:00")],
                                   [evaluated(plausibility=risk), evaluated()])
    first = result["iterations"][0]
    assert first["critic_evaluation"]["overall"] == 4.25
    assert first["validation"]["valid"] and first["validation"]["violations"] == []
    assert first["acceptance_policy"] == {
        "numeric_criteria_passed": True, "plausibility_revision_required": True,
        "accepted": False, "revision_causes": ["plausibility_revision_required"]}
    assert result["status"] == "proposal_ready" and result["refinements"] == 1
    assert "gym_mon" in proposer.calls[1][0] and "20:15" in proposer.calls[1][0]
    assert "Explore more transition time" in proposer.calls[1][0]
    assert "lacks the full user constraints" in proposer.calls[1][0]
    assert len(critic.calls) == 2
    assert first["result_calendar"] != result["iterations"][1]["result_calendar"]


def test_same_operations_can_be_accepted_after_grounded_rationale_revision(context):
    first = candidate()
    revised = first.model_copy(deep=True)
    revised.rationale.summary = (
        "Kept the same study blocks after checking the available context. The calendar gives no "
        "gym location or post-gym routine, so immediate focused study remains uncertain. "
        "Moving study later would shorten the available time under the evening preference; "
        "the user should confirm if a transition is needed.")
    concern = review(True, "moderate",
                     "new_0 begins at 20:15 shortly after gym_mon ends at 20:00; check practical transition",
                     "Reassess whether a transition is needed; keep operations if justified")
    response = review(False, "moderate",
                      "Prior transition concern was considered; the revised rationale acknowledges missing "
                      "routine information and explains the trade-off, so no further scheduling revision is required", "")
    result, proposer, critic = run(context, [first, revised],
                                   [evaluated(plausibility=concern), evaluated(plausibility=response)])
    assert result["status"] == "proposal_ready" and result["refinements"] == 1
    second = result["iterations"][1]
    assert second["operations_changed_from_previous"] is False
    assert second["rationale_changed_from_previous"] is True
    assert second["proposal"]["changes"] == result["initial_proposal"]["changes"]
    assert second["acceptance_policy"]["accepted"] is True
    assert "keep exactly the same operations" in proposer.calls[1][0]
    assert "do not invent" in proposer.calls[1][0]
    second_packet = json.loads(critic.calls[1][0].split("\n", 1)[1])
    assert second_packet["prior_critic_reviews"][0]["plausibility_review"]["reason"] == concern.reason
    assert second_packet["prior_critic_reviews"][0]["proposal"]["rationale"] == first.rationale.model_dump()
    assert second_packet["proposal"]["rationale"]["summary"] == revised.rationale.summary


def test_repeated_technical_validity_does_not_force_critic_acceptance(context):
    repeated = candidate()
    concern = review(True, "moderate",
                     "new_0 still starts at 20:15 after gym_mon; the practical transition remains unexplained",
                     "Check whether the user needs transition time or acknowledge unresolved uncertainty")
    result, proposer, critic = run(context, [repeated] * 4,
                                   [evaluated(plausibility=concern)] * 4)
    assert result["status"] == "deferred_critic_threshold"
    assert result["refinements"] == 3 and not result["critic_accepted"]
    assert all(step["operations_changed_from_previous"] is False for step in result["iterations"][1:])
    assert all(step["rationale_changed_from_previous"] is False for step in result["iterations"][1:])
    assert [len(step["prior_critic_reviews"]) for step in result["iterations"]] == [0, 1, 2, 3]
    assert "Repeating technical validity alone" in proposer.calls[1][0]
    assert len(critic.calls) == 4


def test_previous_review_context_excludes_original_request_and_profile(context):
    root, source = context
    source.user_request = "PRIVATE_REQUEST_MARKER"
    source.profile.description = "PRIVATE_PROFILE_MARKER"
    concern = review(True, "moderate", "new_0 may need a practical transition", "Reassess the transition")
    _, proposer, critic = run((root, source), [candidate(), candidate()],
                              [evaluated(plausibility=concern), evaluated()])
    assert "PRIVATE_REQUEST_MARKER" in proposer.calls[1][0]
    assert "PRIVATE_PROFILE_MARKER" in proposer.calls[1][0]
    assert "PRIVATE_REQUEST_MARKER" not in critic.calls[1][0]
    assert "PRIVATE_PROFILE_MARKER" not in critic.calls[1][0]


def test_score_425_without_revision_accepts_even_with_observation(context):
    observation = review(False, "moderate",
                         "new_0 follows gym_mon after a short gap, but impact is uncertain", "")
    result, proposer, critic = run(context, [candidate()], [evaluated(plausibility=observation)])
    assert result["status"] == "proposal_ready" and result["refinements"] == 0
    assert result["iterations"][0]["acceptance_policy"]["accepted"] is True
    assert result["iterations"][0]["critic_evaluation"]["plausibility_review"]["severity"] == "moderate"
    assert len(proposer.calls) == len(critic.calls) == 1


def test_low_score_without_plausibility_request_still_revises(context):
    result, proposer, _ = run(context, [candidate(), candidate("2026-11-09T21:00:00+00:00")],
                              [evaluated((3, 4, 4, 4)), evaluated()])
    assert result["iterations"][0]["acceptance_policy"]["revision_causes"] == ["numeric_criteria_failed"]
    assert "Numeric Critic criteria failed" in proposer.calls[1][0]
    assert result["status"] == "proposal_ready" and result["refinements"] == 1


def test_both_failures_reach_proposer(context):
    risk = review(True, "high", "new_0 conflicts with concrete event context",
                  "Explore another feasible slot")
    result, proposer, _ = run(context, [candidate(), candidate("2026-11-09T21:00:00+00:00")],
                              [evaluated((3, 4, 4, 4), risk), evaluated()])
    assert result["iterations"][0]["acceptance_policy"]["revision_causes"] == [
        "numeric_criteria_failed", "plausibility_revision_required"]
    assert "Numeric Critic criteria failed" in proposer.calls[1][0]
    assert "Plausibility revision required" in proposer.calls[1][0]
    assert "Explore another feasible slot" in proposer.calls[1][0]


def test_persistent_plausibility_request_stops_after_three_revisions(context):
    risk = review(True, "moderate", "new_0 follows gym_mon with a material contextual risk",
                  "Explore another arrangement if feasible")
    result, proposer, critic = run(context, [candidate()] * 4, [evaluated(plausibility=risk)] * 4)
    assert result["status"] == "deferred_critic_threshold"
    assert result["decision"] == "defer" and not result["critic_accepted"]
    assert result["refinements"] == 3
    assert len(result["iterations"]) == len(proposer.calls) == len(critic.calls) == 4
    assert all(step["acceptance_policy"]["numeric_criteria_passed"] for step in result["iterations"])
    assert result["reasons"] == ["plausibility_revision_required"]
    assert result["unresolved_plausibility_review"]["reason"] == risk.reason


def test_valid_proposal_with_minor_risk_does_not_force_revision(context):
    observation = review(False, "low", "new_0 follows gym_mon, but the gap may suffice", "")
    result, _, _ = run(context, [candidate()], [evaluated(plausibility=observation)])
    assert result["status"] == "proposal_ready"
    assert result["iterations"][0]["critic_evaluation"]["plausibility_review"]["reason"] == observation.reason


def test_new_contract_rejects_missing_or_inconsistent_review(context):
    legacy = CriticEvaluation(scores=CriticScores(reasoning=4, coherence=5,
                                                  alternatives=4, clarity=4),
                              weaknesses=[], feedback="Old evaluation")
    assert legacy.plausibility_review is None
    with pytest.raises(ValidationError):
        CurrentCriticEvaluation.model_validate(legacy.model_dump(exclude_none=True))
    for invalid in [
        {"revision_required": True, "severity": "none", "reason": "x", "suggested_improvement": "y"},
        {"revision_required": True, "severity": "moderate", "reason": "", "suggested_improvement": "y"},
        {"revision_required": True, "severity": "moderate", "reason": "x", "suggested_improvement": ""},
        {"revision_required": False, "severity": "low", "reason": "", "suggested_improvement": ""},
        {"revision_required": "true", "severity": "moderate", "reason": "x", "suggested_improvement": "y"},
    ]:
        with pytest.raises(ValidationError):
            PlausibilityReview.model_validate(invalid)
    provider = ScriptedProvider([legacy])
    source = context[1]
    events, validation = simulate(source, candidate())
    from critic import final_calendar_view
    calendar = final_calendar_view(events, candidate(),
                                   original_ids={event.id for event in source.calendar.events},
                                   timezone=source.profile.timezone)
    with pytest.raises(LLMError, match="missing or inconsistent"):
        critique(candidate(), final_calendar=calendar, technical_validation=validation, provider=provider)


def test_a_baseline_unchanged_and_b_records_version(context):
    root, source = context
    a = json.loads(run_a(root, source.scenario_id, ScriptedProvider([candidate()])).read_text())
    b_path = run_b(root, source.scenario_id, ScriptedProvider([candidate()]),
                   ScriptedProvider([evaluated()]))
    b = json.loads(b_path.read_text())
    assert a["configuration"] == "A" and "critic_policy_version" not in a
    assert b["critic_policy_version"] == CRITIC_POLICY_VERSION
    assert b["prompt_versions"]["proposer_sha256"] == a["prompt_versions"]["proposer_sha256"]
    assert "proposer_revision_sha256" in b["prompt_versions"]
    assert "proposer_revision_sha256" not in a["prompt_versions"]
    assert a["decision"] == b["decision"] == "act"
    artifact = json.loads(import_result(root, b_path).read_text())
    assert artifact["critic_policy_version"] == CRITIC_POLICY_VERSION
    assert artifact["iterations"][0]["acceptance_policy"]["accepted"]


def test_streamlit_reads_reassessment_history(context, tmp_path):
    root, source = context
    first = candidate()
    revised = first.model_copy(deep=True)
    revised.rationale.summary = "Same operations after rechecking the practical transition uncertainty."
    concern = review(True, "moderate", "new_0 may need a transition after gym_mon",
                     "Reassess the practical sequence")
    path = run_b(root, source.scenario_id, ScriptedProvider([first, revised]),
                 ScriptedProvider([evaluated(plausibility=concern), evaluated()]))
    import_result(root, path)
    wrapper = tmp_path / "review_ui.py"
    wrapper.write_text(f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n"
                       f"from pathlib import Path\nimport annotation_app\n"
                       f"annotation_app.ROOT = Path({str(root)!r})\nannotation_app.main()\n")
    app = AppTest.from_file(wrapper, default_timeout=10).run()
    assert not app.exception
    assert any("Política do Critic: plausibility_review_v1" in x.value for x in app.caption)
    assert any("Reavaliação da dúvida anterior" in x.value for x in app.caption)
