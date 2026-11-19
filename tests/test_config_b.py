"""Active schema-2 B cycle and A/B baseline regressions with scripted providers."""
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))

from benchmark_v2 import import_scenario
from calendar_v2 import simulate
from critic import critique
from llm import IAeduProvider, LLMError
from models import Change, CurrentCriticEvaluation, CriticScores, PlausibilityReview, Proposal, Rationale
from pipeline_b import CriticSettings, run_config_b
from proposer_v2 import V2RuntimeScenario, propose_v2
from rules import rule_based_decision
from run_config_a_v2 import run_one as run_a
from run_config_b_v2 import run_one as run_b
from scenario_v2 import load_scenario
from compare_runs import collect


class ScriptedProvider:
    name = "iaedu"
    model = "GPT-5.5-mock"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def generation_config(self):
        return {"test": "scripted"}

    def generate_structured(self, prompt, schema, *, system=""):
        self.calls.append((prompt, schema, system))
        result = self.outputs.pop(0)
        if isinstance(result, Exception):
            raise result
        assert isinstance(result, schema)
        return result


@pytest.fixture
def context(tmp_path):
    path = import_scenario(tmp_path, ROOT.parent / "scenario_v2_example.json", "train")
    return tmp_path, load_scenario(path)


def proposal(start="2026-11-09T20:00:00+00:00", *, event_id="gym_mon"):
    return Proposal(changes=[Change(type="move", event_id=event_id, to_start=start)],
                    rationale=Rationale(constraints=["work fixed"],
                                        priorities=["study before gym"],
                                        alternatives_considered=[], summary="Move gym."))


def evaluation(score, feedback="Explain alternatives"):
    return CurrentCriticEvaluation(scores=CriticScores(reasoning=score, coherence=score,
                                                alternatives=score, clarity=score),
                            weaknesses=["alternative not explained"] if score < 4 else [],
                            feedback=feedback, plausibility_review=PlausibilityReview(
                                revision_required=False, severity="none", reason="", suggested_improvement=""),
                            unresolved_assumptions=[])


def run(context, proposals, reviews, settings=None, simulator=None):
    _, scenario = context
    proposer, critic = ScriptedProvider(proposals), ScriptedProvider(reviews)
    result = run_config_b(scenario.profile, V2RuntimeScenario(scenario),
                          proposer_provider=proposer, critic_provider=critic,
                          settings=settings, proposer_fn=propose_v2,
                          simulate_fn=simulator or (lambda candidate: simulate(scenario, candidate)))
    return result, proposer, critic


def test_critic_accepts_first_and_uses_same_rules(context):
    result, proposer, critic = run(context, [proposal()], [evaluation(5)])
    assert result["status"] == "proposal_ready" and result["decision"] == "act"
    assert result["refinements"] == 0
    assert len(proposer.calls) == len(critic.calls) == 1
    assert result["decision"] == rule_based_decision(proposal(), context[1].calendar.events, [])[0]
    assert result["iterations"][0]["validation"]["violations"] == []


def test_critic_feedback_revises_proposal(context):
    first, revised = proposal(), proposal("2026-11-09T21:00:00+00:00")
    result, proposer, critic = run(context, [first, revised], [evaluation(2), evaluation(5)])
    assert result["critic_accepted"] and result["refinements"] == 1
    assert result["initial_proposal"] != result["final_proposal"]
    assert [step["critic_evaluation"]["overall"] for step in result["iterations"]] == [2, 5]
    assert "REVIEWER FEEDBACK" not in proposer.calls[1][0]  # v2 adapter uses its own prompt wording
    assert "Reviewer feedback" in proposer.calls[1][0]
    assert first.model_dump_json() in proposer.calls[1][0]
    assert "alternative not explained" in proposer.calls[1][0]


def test_max_three_refinements_and_threshold(context):
    result, proposer, critic = run(context, [proposal()] * 4, [evaluation(3)] * 4)
    assert result["status"] == "deferred_critic_threshold" and result["decision"] == "defer"
    assert result["refinements"] == 3
    assert len(result["iterations"]) == len(proposer.calls) == len(critic.calls) == 4
    result, _, _ = run(context, [proposal()], [evaluation(4)], CriticSettings(threshold=4.5, max_refinements=0))
    assert result["decision"] == "defer"
    with pytest.raises(ValueError):
        CriticSettings(max_refinements=-1)


def test_invalid_proposal_skips_critic_and_can_be_revised(context):
    invalid = proposal(event_id="work_mon")
    result, proposer, critic = run(context, [invalid, proposal()], [evaluation(5)],
                                   CriticSettings(max_refinements=1))
    assert result["iterations"][0]["validation"]["violations"]
    assert result["iterations"][0]["critic_evaluation"] is None
    assert len(critic.calls) == 1
    assert result["decision"] == "act" and result["refinements"] == 1
    assert "Deterministic validation" in proposer.calls[1][0]
    result, _, critic = run(context, [invalid], [], CriticSettings(max_refinements=0))
    assert result["status"] == "deferred_invalid_proposal" and not critic.calls


def test_technical_failures_never_act(context):
    result, _, _ = run(context, [proposal()], [LLMError("HTTP 503")])
    assert result["status"] == "critic_error" and result["decision"] is None
    assert result["safe_action"] == "no_autonomous_action"
    result, _, critic = run(context, [LLMError("invalid JSON")], [])
    assert result["status"] == "proposer_error" and not critic.calls
    def broken(*args):
        raise ValueError("internal validator error")
    result, _, critic = run(context, [proposal()], [], simulator=broken)
    assert result["status"] == "validation_error" and result["decision"] is None
    assert not critic.calls


def test_critic_acceptance_does_not_override_fixed_defer_rule(context):
    many = Proposal(changes=[Change(type="move", event_id="gym_mon", to_start="2026-11-09T20:00:00+00:00"),
                             Change(type="add", title="Study", to_start="2026-11-09T18:30:00+00:00"),
                             Change(type="add", title="More study", to_start="2026-11-10T20:00:00+00:00")],
                    rationale=proposal().rationale)
    result, _, _ = run(context, [many], [evaluation(5)])
    assert result["critic_accepted"] and result["decision"] == "defer"
    assert result["decision"] == rule_based_decision(many, context[1].calendar.events, [])[0]
    assert "mais de 2 mudanças" in result["reasons"]


def test_critic_sees_result_calendar_without_original_request_or_profile(context):
    root, scenario = context
    scenario.profile.description = "PRIVATE_PROFILE_MARKER"
    scenario.user_request = "PRIVATE_REQUEST_MARKER"
    result, proposer, critic = run((root, scenario), [proposal()], [evaluation(5)])
    critic_prompt, schema, system = critic.calls[0]
    assert schema is CurrentCriticEvaluation
    assert "PRIVATE_PROFILE_MARKER" not in critic_prompt + system
    assert "PRIVATE_REQUEST_MARKER" not in critic_prompt + system
    packet = json.loads(critic_prompt.split("\n", 1)[1])
    assert packet["proposal"] == proposal().model_dump(mode="json")
    assert packet["final_calendar"]["timezone"] == "Europe/Lisbon"
    assert {event["id"] for event in packet["final_calendar"]["events"]} == {
        event.id for event in scenario.calendar.events}
    assert next(event for event in packet["final_calendar"]["events"]
                if event["id"] == "work_tue")["change_status"] == "preserved"
    assert "profile" not in packet and "user_request" not in packet
    assert "PRIVATE_PROFILE_MARKER" in proposer.calls[0][0]
    assert result["status"] == "proposal_ready"


def test_iaedu_stream_mock_carries_result_calendar(monkeypatch, context):
    captured = []
    response = Mock()
    payload = evaluation(4).model_dump_json()
    response.iter_lines.return_value = [
        json.dumps({"type": "token", "content": payload[:30]}).encode(),
        json.dumps({"type": "token", "content": payload[30:]}).encode(),
    ]
    def post(url, **kwargs):
        captured.append(kwargs)
        return response
    monkeypatch.setattr(requests, "post", post)
    client = IAeduProvider(api_key="test-only", endpoint="https://example.invalid/stream",
                          channel_id="synthetic-channel")
    scenario = context[1]
    events, validation = simulate(scenario, proposal())
    from critic import final_calendar_view
    calendar = final_calendar_view(events, proposal(), original_ids={e.id for e in scenario.calendar.events},
                                   timezone=scenario.profile.timezone)
    result = critique(proposal(), final_calendar=calendar, technical_validation=validation, provider=client)
    assert result.overall == 4
    transmitted = json.loads(captured[0]["files"]["message"][1].split(
        "Assess this structured proposal and its resulting calendar:\n", 1)[1])
    assert transmitted["proposal"] == proposal().model_dump(mode="json")
    assert transmitted["final_calendar"] == calendar
    assert captured[0]["headers"] == {"x-api-key": "test-only"}


def test_iaedu_mock_rejects_new_response_without_plausibility_review(monkeypatch, context):
    legacy = {"scores": {"reasoning": 4, "coherence": 5,
                         "alternatives": 4, "clarity": 4},
              "weaknesses": [], "feedback": "No revision suggested"}
    calls = []
    def post(url, **kwargs):
        calls.append(kwargs)
        response = Mock()
        response.iter_lines.return_value = [json.dumps({"type": "token", "content": json.dumps(legacy)}).encode()]
        return response
    monkeypatch.setattr(requests, "post", post)
    client = IAeduProvider(api_key="test-only", endpoint="https://example.invalid/stream",
                          channel_id="synthetic-channel")
    scenario = context[1]
    events, validation = simulate(scenario, proposal())
    from critic import final_calendar_view
    calendar = final_calendar_view(events, proposal(), original_ids={e.id for e in scenario.calendar.events},
                                   timezone=scenario.profile.timezone)
    with pytest.raises(LLMError, match="respostas sem JSON válido"):
        critique(proposal(), final_calendar=calendar, technical_validation=validation, provider=client)
    assert len(calls) == 2


def test_a_b_runners_and_compare_metadata(context):
    root, scenario = context
    a_path = run_a(root, scenario.scenario_id, ScriptedProvider([proposal()]),
                   experiment_id="paired", repeat_index=2)
    b_path = run_b(root, scenario.scenario_id, ScriptedProvider([proposal()]),
                   ScriptedProvider([evaluation(5)]), experiment_id="paired", repeat_index=2)
    a, b = (json.loads(path.read_text()) for path in (a_path, b_path))
    assert a["status"] == b["status"] == "proposal_ready"
    assert a["configuration"] == "A" and b["configuration"] == "B"
    assert a["decision"] == b["decision"] == "act"
    assert a_path.parent.name == "A" and b_path.parent.name == "B"
    rows = collect(root / "eval" / "runs", "paired")
    assert len(rows) == 1 and rows[0]["paired"] and rows[0]["same_proposer_model"]
