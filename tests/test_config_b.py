"""Ciclo B com fornecedores simulados, sem chamadas à API."""
import json
import sys
from pathlib import Path

import pytest
import requests
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))

from critic import critique  # noqa: E402
from llm import IAeduProvider, LLMError  # noqa: E402
from models import Change, CriticEvaluation, CriticScores, Profile, Proposal, Rationale, Scenario  # noqa: E402
from pipeline_b import CriticSettings, run_config_b  # noqa: E402
from rules import rule_based_decision  # noqa: E402


class ScriptedProvider:
    name = "iaedu"
    model = "GPT-5.5"

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
def context():
    profile = Profile.model_validate_json((ROOT / "data" / "profile.json").read_text())
    scenario = Scenario.model_validate_json(
        (ROOT / "data" / "scenarios" / "soft_gym_01.json").read_text())
    return profile, scenario


def proposal(start="2026-11-11T20:00", *, event_id="gym_wed"):
    return Proposal(changes=[Change(type="move", event_id=event_id, to_start=start)],
                    rationale=Rationale(constraints=["fixed classes"],
                                        priorities=["deadline before gym"],
                                        alternatives_considered=[], summary="Move gym."))


def evaluation(score, feedback="Explain the rejected alternative."):
    return CriticEvaluation(scores=CriticScores(reasoning=score, coherence=score,
                                                alternatives=score, clarity=score),
                            weaknesses=["alternative not explained"] if score < 4 else [],
                            feedback=feedback)


def run(context, proposals, reviews, settings=None):
    proposer = ScriptedProvider(proposals)
    critic = ScriptedProvider(reviews)
    result = run_config_b(*context, proposer_provider=proposer, critic_provider=critic,
                          settings=settings)
    return result, proposer, critic


def test_critic_approves_first_and_reuses_a_rules(context):
    result, proposer, critic = run(context, [proposal()], [evaluation(5)])
    assert result["status"] == "proposal_ready"
    assert result["decision"] == "act"
    assert result["refinements"] == 0
    assert len(proposer.calls) == len(critic.calls) == 1
    assert result["decision"] == rule_based_decision(proposal(), context[1].calendar, [])[0]
    assert result["iterations"][0]["validation"]["violations"] == []


def test_critic_rejects_and_proposer_revises_with_feedback(context):
    first, revised = proposal(), proposal("2026-11-11T21:00")
    result, proposer, critic = run(context, [first, revised],
                                   [evaluation(2), evaluation(5)])
    assert result["critic_accepted"] and result["refinements"] == 1
    assert result["initial_proposal"] != result["final_proposal"]
    assert [step["critic_evaluation"]["overall"] for step in result["iterations"]] == [2, 5]
    assert "REVIEWER FEEDBACK" in proposer.calls[1][0]
    assert "alternative not explained" in proposer.calls[1][0]
    assert first.model_dump_json(indent=1) in proposer.calls[1][0]


def test_never_reaches_threshold_and_respects_three_revision_limit(context):
    result, proposer, critic = run(context, [proposal()] * 4, [evaluation(3)] * 4)
    assert result["status"] == "deferred_critic_threshold"
    assert result["decision"] == "defer" and not result["critic_accepted"]
    assert result["refinements"] == 3
    assert len(result["iterations"]) == len(proposer.calls) == len(critic.calls) == 4


def test_invalid_proposal_skips_critic_and_cannot_act(context):
    invalid = proposal("2026-11-11T10:30")
    result, proposer, critic = run(
        context, [invalid, proposal()], [evaluation(5)],
        CriticSettings(max_refinements=1))
    assert result["iterations"][0]["validation"]["violations"]
    assert result["iterations"][0]["critic_evaluation"] is None
    assert len(critic.calls) == 1
    assert result["decision"] == "act" and result["refinements"] == 1
    assert "Deterministic validation" in proposer.calls[1][0]

    result, _, critic = run(context, [invalid], [], CriticSettings(max_refinements=0))
    assert result["status"] == "deferred_invalid_proposal"
    assert result["decision"] == "defer" and not critic.calls


def test_critic_failure_is_error_without_autonomous_action(context):
    result, _, _ = run(context, [proposal()], [LLMError("IAedu HTTP 503")])
    assert result["status"] == "critic_error"
    assert result["decision"] is None
    assert result["safe_action"] == "no_autonomous_action"
    assert result["error_stage"] == "critic"


def test_proposer_invalid_response_is_technical_error(context):
    result, _, critic = run(context, [LLMError("JSON inválido")], [])
    assert result["status"] == "proposer_error" and result["decision"] is None
    assert not critic.calls


def test_validator_failure_is_recorded_as_technical_error(context, monkeypatch):
    import pipeline_b

    def fail(*args):
        raise ValueError("erro interno")

    monkeypatch.setattr(pipeline_b, "find_violations", fail)
    result, _, critic = run(context, [proposal()], [])
    assert result["status"] == "validation_error"
    assert result["decision"] is None
    assert result["safe_action"] == "no_autonomous_action"
    assert not critic.calls


def test_accepted_critic_does_not_override_a_rule_defer(context):
    sensitive = proposal(event_id="gym_wed")
    sensitive.changes.append(Change(type="add", title="Work", to_start="2026-11-10T18:00"))
    sensitive.changes.append(Change(type="add", title="More work", to_start="2026-11-12T18:00"))
    result, _, _ = run(context, [sensitive], [evaluation(5)])
    assert result["critic_accepted"]
    assert result["decision"] == "defer"
    assert result["decision"] == rule_based_decision(sensitive, context[1].calendar, [])[0]
    assert "mais de 2 mudanças" in result["reasons"]


def test_critic_sees_only_proposal_and_not_private_context(context):
    profile, scenario = context
    profile.priorities[0].category = "PRIVATE_PROFILE_MARKER"
    scenario.user_request = "PRIVATE_REQUEST_MARKER"
    result, _, critic = run((profile, scenario), [proposal()], [evaluation(5)])
    critic_prompt, schema, system = critic.calls[0]
    assert schema is CriticEvaluation
    assert "PRIVATE_PROFILE_MARKER" not in critic_prompt + system
    assert "PRIVATE_REQUEST_MARKER" not in critic_prompt + system
    assert critic_prompt == "Assess this proposal and its rationale only:\n" + proposal().model_dump_json(indent=2)
    assert result["status"] == "proposal_ready"


def test_critic_uses_iaedu_stream_with_only_proposal(monkeypatch):
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
    result = critique(proposal(), provider=client)
    assert result.overall == 4
    message = captured[0]["files"]["message"][1]
    assert proposal().model_dump_json(indent=2) in message
    assert "You do not know the original user" in message
    assert captured[0]["headers"] == {"x-api-key": "test-only"}


def test_threshold_and_dimension_minimum_are_configurable(context):
    result, _, _ = run(context, [proposal()], [evaluation(4)],
                       CriticSettings(threshold=4.5, max_refinements=0))
    assert result["decision"] == "defer"
    with pytest.raises(ValueError):
        CriticSettings(max_refinements=-1)


def test_configuration_a_still_runs_with_same_rules(context, monkeypatch, tmp_path):
    import run_config_a

    (tmp_path / "data" / "scenarios").mkdir(parents=True)
    (tmp_path / "data" / "profile.json").write_text(context[0].model_dump_json())
    (tmp_path / "data" / "scenarios" / "soft_gym_01.json").write_text(
        context[1].model_dump_json())
    proposer = ScriptedProvider([proposal()])
    monkeypatch.setattr(run_config_a, "ROOT", tmp_path)
    monkeypatch.setattr(run_config_a, "get_provider", lambda **kwargs: proposer)
    monkeypatch.setattr(sys, "argv", ["run_config_a.py", "--only", "soft_gym_01"])
    run_config_a.main()
    result_file = next((tmp_path / "eval" / "runs").glob("*/A/soft_gym_01.json"))
    result = json.loads(result_file.read_text())
    assert result["decision"] == "act"
    assert result["status"] == "proposal_ready"
    assert result["configuration"] == "A" and result["run_id"]
    assert result["family"] == context[1].family
    assert len(proposer.calls) == 1


def test_configuration_b_runner_records_run_identity(context, monkeypatch, tmp_path):
    import run_config_b as runner_b

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "profile.json").write_text(context[0].model_dump_json())
    proposer = ScriptedProvider([proposal()])
    critic = ScriptedProvider([evaluation(5)])
    monkeypatch.setattr(runner_b, "ROOT", tmp_path)
    monkeypatch.setattr(runner_b, "load_scenarios", lambda only: [context[1]])
    monkeypatch.setattr(runner_b, "get_provider",
                        lambda role, **kwargs: proposer if role == "PROPOSER" else critic)
    monkeypatch.setattr(sys, "argv", ["run_config_b.py", "--only", "soft_gym_01",
                                  "--experiment-id", "pilot", "--repeat-index", "2"])
    assert runner_b.main() == 0
    path = next((tmp_path / "eval" / "runs").glob("*/B/soft_gym_01.json"))
    record = json.loads(path.read_text())
    assert record["run_id"] == path.parent.parent.name
    assert record["experiment_id"] == "pilot" and record["repeat_index"] == 2
    assert record["configuration"] == "B" and record["family"] == context[1].family
    assert record["decision"] == "act" and record["seconds"] >= 0
