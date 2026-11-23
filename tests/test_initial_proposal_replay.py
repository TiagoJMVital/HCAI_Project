"""B-run replay is tested only with scripted providers and temporary files."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "eval")]

from benchmark_v2 import import_scenario
from calendar_v2 import simulate
from models import (Change, CriticScores, CurrentCriticEvaluation,
                    PlausibilityReview, Proposal, Rationale)
from proposal_catalog_v2 import import_result
from run_config_b_v2 import load_initial_proposal, run_one
from scenario_v2 import load_manifest, load_scenario


class ScriptedProvider:
    name = "mock"
    model = "scripted"

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def generation_config(self):
        return {"scripted": True}

    def generate_structured(self, prompt, schema, *, system=""):
        self.calls.append((prompt, system))
        value = self.answers.pop(0)
        return schema.from_proposal(value) if isinstance(value, Proposal) and hasattr(schema, "from_proposal") else value


def proposal(hour="20:00"):
    return Proposal(
        changes=[Change(type="add", title="Assessment preparation",
                        to_start=f"2026-11-09T{hour}:00+00:00",
                        to_end="2026-11-09T21:30:00+00:00")],
        rationale=Rationale(constraints=["work is fixed"], priorities=["study"],
                            alternatives_considered=[], summary="Study after gym"))


def evaluation(revise=False):
    return CurrentCriticEvaluation(
        scores=CriticScores(reasoning=4, coherence=5, alternatives=4, clarity=4),
        weaknesses=["new_0 follows gym_mon"] if revise else [],
        feedback="Reassess transition" if revise else "No further revision needed",
        plausibility_review=PlausibilityReview(
            revision_required=revise, severity="moderate" if revise else "none",
            reason="new_0 starts directly after gym_mon at 20:00" if revise else "",
            suggested_improvement="Consider a later start if feasible" if revise else ""),
        unresolved_assumptions=[])


@pytest.fixture
def prepared(tmp_path):
    path = import_scenario(tmp_path, ROOT / "data/scenarios/working_student_deadline_001.json", "train")
    source = run_one(tmp_path, "working_student_deadline_001",
                     ScriptedProvider([proposal()]), ScriptedProvider([evaluation()]))
    return tmp_path, load_scenario(path), source


def test_replay_skips_initial_proposer_and_reconstructs_calendar(prepared):
    root, scenario, source = prepared
    source_bytes = source.read_bytes()
    proposer, critic = ScriptedProvider([]), ScriptedProvider([evaluation()])
    new_path = run_one(root, scenario.scenario_id, proposer, critic,
                       initial_proposal_from=source)
    result = json.loads(new_path.read_text())
    original = json.loads(source_bytes)
    assert new_path != source and source.read_bytes() == source_bytes
    assert proposer.calls == [] and len(critic.calls) == 1
    assert result["initial_proposal"] == original["initial_proposal"]
    assert result["iterations"][0]["proposer_source"] == "replayed"
    assert result["iterations"][0]["result_calendar"] == original["iterations"][0]["result_calendar"]
    assert result["iterations"][0]["validation"] == original["iterations"][0]["validation"]
    assert result["status"] == "proposal_ready" and result["refinements"] == 0
    assert result["replay_source"]["source_run_sha256"] == hashlib.sha256(source_bytes).hexdigest()
    assert result["replay_source"]["source_run_id"] == original["run_id"]
    assert result["replay_source"]["source_calendar_verified_against_current_simulator"] is True
    assert "quality-control reviewer" in critic.calls[0][1]
    assert json.loads(critic.calls[0][0].split("\n", 1)[1])["final_calendar"] == result["final_result_calendar"]
    imported = json.loads(import_result(root, new_path).read_text())
    assert imported["replay_source"] == result["replay_source"]


def test_replay_then_normal_proposer_revision(prepared):
    root, scenario, source = prepared
    proposer, critic = ScriptedProvider([proposal("21:00")]), ScriptedProvider([
        evaluation(True), evaluation(False)])
    result = json.loads(run_one(root, scenario.scenario_id, proposer, critic,
                                initial_proposal_from=source).read_text())
    assert result["status"] == "proposal_ready" and result["refinements"] == 1
    assert [step["proposer_source"] for step in result["iterations"]] == ["replayed", "generated"]
    assert len(proposer.calls) == 1 and len(critic.calls) == 2
    assert "new_0 starts directly after gym_mon" in proposer.calls[0][0]
    assert "Consider a later start" in proposer.calls[0][0]
    assert result["iterations"][0]["result_calendar"] != result["iterations"][1]["result_calendar"]
    assert result["iterations"][1]["validation"] == simulate(
        scenario, Proposal.model_validate(result["final_proposal"]))[1]


def test_replay_respects_three_revision_limit(prepared):
    root, scenario, source = prepared
    proposer, critic = ScriptedProvider([proposal()] * 3), ScriptedProvider([evaluation(True)] * 4)
    result = json.loads(run_one(root, scenario.scenario_id, proposer, critic,
                                initial_proposal_from=source).read_text())
    assert result["status"] == "deferred_critic_threshold"
    assert result["refinements"] == 3
    assert len(result["iterations"]) == len(critic.calls) == 4
    assert len(proposer.calls) == 3


@pytest.mark.parametrize("change", [
    lambda record: record.update(scenario_id="another"),
    lambda record: record.update(family="another"),
    lambda record: record.update(profile_id="another"),
    lambda record: record.update(split="test"),
    lambda record: record.update(configuration="A"),
    lambda record: record.update(initial_proposal=None),
    lambda record: record["iterations"][0]["result_calendar"]["events"][0].update(title="tampered"),
])
def test_replay_rejects_wrong_or_tampered_source_before_provider_calls(prepared, change):
    root, scenario, source = prepared
    altered = json.loads(source.read_text())
    change(altered)
    tampered = root / "tampered.json"
    tampered.write_text(json.dumps(altered))
    proposer, critic = ScriptedProvider([]), ScriptedProvider([])
    with pytest.raises((ValueError, TypeError)):
        run_one(root, scenario.scenario_id, proposer, critic,
                initial_proposal_from=tampered)
    assert proposer.calls == critic.calls == []


def test_known_historical_run_is_replayable_read_only():
    path = ROOT / "eval/runs/e9052e6757c14820a06b89ddaf9aafe6/B/working_student_deadline_001.json"
    if not path.exists():
        pytest.skip("local historical run is not checked into the repository")
    scenario = load_scenario(ROOT / "data/scenarios/working_student_deadline_001.json")
    row = next(row for row in load_manifest(ROOT) if row["scenario_id"] == scenario.scenario_id)
    before = path.read_bytes()
    initial, provenance = load_initial_proposal(ROOT, path, scenario, row)
    assert len(initial.changes) == 2
    assert all(change.to_start.endswith("20:00:00+00:00") for change in initial.changes)
    assert provenance["source_calendar_verified_against_current_simulator"]
    assert path.read_bytes() == before


def test_historical_initial_proposal_runs_under_current_critic_contract(tmp_path):
    source = ROOT / "eval/runs/e9052e6757c14820a06b89ddaf9aafe6/B/working_student_deadline_001.json"
    if not source.exists():
        pytest.skip("local historical run is not checked into the repository")
    import_scenario(tmp_path, ROOT / "data/scenarios/working_student_deadline_001.json", "train")
    before = source.read_bytes()
    proposer = ScriptedProvider([])
    result_path = run_one(tmp_path, "working_student_deadline_001", proposer,
                          ScriptedProvider([evaluation()]), initial_proposal_from=source)
    result = json.loads(result_path.read_text())
    assert proposer.calls == []
    assert result["initial_proposal"] == json.loads(before)["initial_proposal"]
    assert result["critic_policy_version"] == "uncertainty_review_v2"
    assert result["final_unresolved_assumptions"] == []
    assert source.read_bytes() == before
