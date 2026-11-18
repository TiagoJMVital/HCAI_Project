"""Synthetic-only v2 workflow tests. All writes use pytest temporary directories."""
import json
import hashlib
import shutil
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))

from annotation_v2 import (ProposalReview, ProposalConsensus, compare, load_review,
                           pair, save_consensus, save_review)
from annotation_v2_ui import preview, records, temporal_overlaps
from benchmark_v2 import import_scenario
from calendar_v2 import simulate
from gate_dataset_v2 import build_rows, features, grouped_folds
from models import Change, CurrentCriticEvaluation, CriticScores, PlausibilityReview, Proposal, Rationale
from proposal_catalog_v2 import catalog, import_result
from run_config_a_v2 import run_one as run_a
from run_config_b_v2 import run_one
from scenario_v2 import V2Scenario, load_manifest, load_scenario


class ScriptedProvider:
    name = "mock"
    model = "mock-gpt"

    def __init__(self, values):
        self.values = list(values)
        self.calls = []

    def generation_config(self):
        return {"simulated": True}

    def generate_structured(self, prompt, schema, *, system=""):
        self.calls.append((prompt, system, schema))
        return self.values.pop(0)


@pytest.fixture
def imported(tmp_path):
    path = import_scenario(tmp_path, ROOT.parent / "scenario_v2_example.json", "train")
    return tmp_path, load_scenario(path)


def proposal():
    return Proposal(changes=[Change(type="move", event_id="gym_mon",
                                    to_start="2026-11-09T20:00:00+00:00")],
                    rationale=Rationale(constraints=["work fixed"], priorities=["assessment"],
                                        alternatives_considered=[], summary="Move solo gym after study."))


def accepted():
    return CurrentCriticEvaluation(scores=CriticScores(reasoning=5, coherence=5, alternatives=5, clarity=5),
                            weaknesses=[], feedback="Clear", plausibility_review=PlausibilityReview(
                                revision_required=False, severity="none", reason="", suggested_improvement=""))


def source(root):
    proposer, critic = ScriptedProvider([proposal()]), ScriptedProvider([accepted()])
    path = run_one(root, "working_student_deadline_001", proposer, critic)
    artifact = import_result(root, path)
    return json.loads(artifact.read_text()), proposer, critic


def test_import_rejects_tampered_critic_calendar(imported):
    root, scenario = imported
    proposer, critic = ScriptedProvider([proposal()]), ScriptedProvider([accepted()])
    path = run_one(root, scenario.scenario_id, proposer, critic)
    record = json.loads(path.read_text())
    record["iterations"][0]["result_calendar"]["events"][0]["title"] = "Tampered"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="differs from deterministic simulation"):
        import_result(root, path)


def test_import_rejects_new_result_without_plausibility_review(imported):
    root, scenario = imported
    path = run_one(root, scenario.scenario_id,
                   ScriptedProvider([proposal()]), ScriptedProvider([accepted()]))
    record = json.loads(path.read_text())
    del record["iterations"][0]["critic_evaluation"]["plausibility_review"]
    path.write_text(json.dumps(record))
    with pytest.raises(ValidationError):
        import_result(root, path)


def test_v2_schema_and_multi_profile(imported):
    root, scenario = imported
    assert scenario.profile.timezone == "Europe/Lisbon"
    assert scenario.calendar.events[0].start.tzinfo is not None
    raw = scenario.model_dump(mode="json")
    raw["profile"]["profile_id"] = "healthcare_worker_02"
    raw["profile"]["description"] = "Healthcare worker with rotating shifts"
    assert V2Scenario.model_validate(raw).profile.profile_id == "healthcare_worker_02"
    assert load_manifest(root)[0]["split"] == "train"
    assert len(list((root / "data/scenarios").glob("*.json"))) == 1


@pytest.mark.parametrize("edit", [
    lambda raw: raw.update(schema_version="3.0"),
    lambda raw: raw.update(now="2026-11-09T09:00:00"),
    lambda raw: raw["calendar"]["events"][0].update(end="2026-11-09T08:00:00+00:00"),
    lambda raw: raw["calendar"]["events"].append(raw["calendar"]["events"][0].copy()),
    lambda raw: raw["profile"]["priorities"].update(work=6),
    lambda raw: raw["profile"]["hard_constraints"].append({
        "id": "missing", "description": "x", "rule_type": "protect_events_by_id", "event_ids": ["absent"]}),
])
def test_v2_rejects_invalid_fields(imported, edit):
    _, scenario = imported
    raw = scenario.model_dump(mode="json")
    edit(raw)
    with pytest.raises(ValidationError):
        V2Scenario.model_validate(raw)


def test_intentional_original_overlap_is_allowed(imported):
    _, scenario = imported
    raw = scenario.model_dump(mode="json")
    raw["calendar"]["events"][3]["start"] = raw["calendar"]["events"][1]["start"]
    assert V2Scenario.model_validate(raw)


def test_family_split_and_active_scenario_directory(imported):
    root, scenario = imported
    raw = scenario.model_dump(mode="json")
    raw["scenario_id"] = "second_variant"
    path = root / "variant.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="opposite split"):
        import_scenario(root, path, "test")
    import_scenario(root, path, "train")
    assert len(load_manifest(root)) == 2
    assert len(list((root / "data/scenarios").glob("*.json"))) == 2
    folds = grouped_folds([
        {"split": "train", "family_id": "family_a", "proposal_id": "p1"},
        {"split": "train", "family_id": "family_a", "proposal_id": "p2"},
        {"split": "train", "family_id": "family_b", "proposal_id": "p3"},
    ], 2)
    assert all({"p1", "p2"} <= set(fold[side]) for fold in folds
               for side in ("train_proposal_ids", "validation_proposal_ids")
               if "p1" in fold[side])
    with pytest.raises(ValueError):
        grouped_folds([{"split": "test", "family_id": "family_a", "proposal_id": "p1"}], 2)


def test_simulation_and_critic_context(imported):
    root, scenario = imported
    after, report = simulate(scenario, proposal())
    assert report["valid"] and after is not None
    assert next(e for e in after if e.id == "gym_mon").end.isoformat().startswith("2026-11-09T21:30")
    invalid = Proposal(changes=[Change(type="move", event_id="work_mon",
                                       to_start="2026-11-09T20:00:00+00:00")], rationale=proposal().rationale)
    assert simulate(scenario, invalid)[0] is None
    missing_tz = Proposal(changes=[Change(type="move", event_id="gym_mon",
                                          to_start="2026-11-09T20:00:00")], rationale=proposal().rationale)
    assert simulate(scenario, missing_tz)[0] is None
    artifact, proposer, critic = source(root)
    assert artifact["technical_validation"]["valid"]
    packet, original, proposed, _ = preview(root, artifact)
    assert proposed is not None
    assert any(event.change_status == "moved" for event in proposed)
    assert any(event.change_status == "preserved" for event in proposed)
    assert any(event.change_status == "previous_position" for event in proposed)
    assert temporal_overlaps(original) == []
    soft_conflict = Proposal(changes=[Change(type="move", event_id="gym_mon",
                                              to_start="2026-11-10T18:30:00+00:00")],
                             rationale=proposal().rationale)
    _, conflict_report = simulate(scenario, soft_conflict)
    assert conflict_report["valid"]
    assert any("new temporal overlap" in warning for warning in conflict_report["warnings"])
    assert "working_student_01" in proposer.calls[0][0]
    critic_prompt = critic.calls[0][0]
    assert "working_student_01" not in critic_prompt
    assert "I need at least three hours" not in critic_prompt
    critic_packet = json.loads(critic_prompt.split("\n", 1)[1])
    assert any(event["id"] == "work_tue" for event in critic_packet["final_calendar"]["events"])
    assert critic.calls[0][2] is CurrentCriticEvaluation


def test_v2_a_and_b_share_proposer_and_rules(imported):
    root, _ = imported
    provider = ScriptedProvider([proposal()])
    a = json.loads(run_a(root, "working_student_deadline_001", provider).read_text())
    b, proposer, _ = source(root)
    assert a["status"] == "proposal_ready" and a["decision"] == "act"
    assert b["source_status"] == "proposal_ready"
    assert provider.calls[0][0] == proposer.calls[0][0]
    assert provider.calls[0][1] == proposer.calls[0][1]
    assert a["prompt_versions"]["proposer_sha256"] == b["prompt_versions"]["proposer_sha256"]


def test_direct_annotation_adjudication_export(imported):
    root, _ = imported
    artifact, _, _ = source(root)
    pid = artifact["proposal_id"]
    for author in ("author_a", "author_b"):
        draft, revision = load_review(root, author, pid)
        save_review(root, author, pid, {**draft.model_dump(), "justification": "draft"}, revision)
        partial, revision = load_review(root, author, pid)
        assert partial.status == "draft"
        completed = {**partial.model_dump(), "status": "complete", "scheduling_acceptable": "yes",
                     "autonomy_decision": "act", "primary_reason": "low_impact",
                     "justification": "Solo flexible move is reversible"}
        save_review(root, author, pid, completed, revision)
    assert compare(root)["complete_pairs"] == [pid]
    assert pair(root, pid)[0].autonomy_decision == "act"
    consensus = {**ProposalConsensus(proposal_id=pid, scenario_id=artifact["scenario_id"],
                                    annotator_ids=["author_a", "author_b"]).model_dump(),
                 "status": "complete", "scheduling_acceptable": "yes", "autonomy_decision": "act",
                 "primary_reason": "low_impact", "justification": "Both agree",
                 "adjudicated_by": "both authors", "original_review_sha256": pair(root, pid)[2]}
    save_consensus(root, pid, consensus)
    rows, exclusions = build_rows(root)
    assert len(rows) == 1 and not exclusions
    assert rows[0]["label"] == "act"
    assert not {"scenario_id", "family_id", "profile_id", "primary_reason", "justification"} & rows[0]["features"].keys()
    with pytest.raises(ValueError, match="locked"):
        build_rows(root, split="test")
    with pytest.raises(ValueError, match="frozen"):
        save_review(root, "author_a", pid, {**pair(root, pid)[0].model_dump()},
                    load_review(root, "author_a", pid)[1])


def test_quality_rejection_has_no_gate_label(imported):
    root, _ = imported
    artifact, _, _ = source(root)
    pid = artifact["proposal_id"]
    with pytest.raises(ValidationError):
        ProposalReview(proposal_id=pid, scenario_id=artifact["scenario_id"], annotator_id="author_a",
                       status="complete", scheduling_acceptable="no", autonomy_decision="defer",
                       primary_reason="high_impact", justification="Bad schedule")
    assert records(root, "author_a")[0]["state"] == "not_started"
    assert build_rows(root)[1][0]["reason"] == "independent_reviews_or_consensus_missing"


def test_completed_quality_rejection_stays_out_of_gate(imported):
    root, _ = imported
    artifact, _, _ = source(root)
    pid = artifact["proposal_id"]
    for author in ("author_a", "author_b"):
        blank, revision = load_review(root, author, pid)
        save_review(root, author, pid, {**blank.model_dump(), "status": "complete",
                    "scheduling_acceptable": "no", "autonomy_decision": None,
                    "primary_reason": "does not meet request", "justification": "insufficient study time"}, revision)
    hashes = pair(root, pid)[2]
    save_consensus(root, pid, {"proposal_id": pid, "scenario_id": artifact["scenario_id"],
                  "annotator_ids": ["author_a", "author_b"], "status": "complete",
                  "scheduling_acceptable": "no", "autonomy_decision": None,
                  "primary_reason": "does not meet request", "justification": "both authors agree",
                  "adjudicated_by": "both authors", "original_review_sha256": hashes})
    rows, exclusions = build_rows(root)
    assert rows == [] and exclusions == [{"proposal_id": pid, "reason": "scheduling_rejected"}]


def test_technical_failure_excluded_without_defer_label(imported):
    root, scenario = imported
    bad = Proposal(changes=[Change(type="delete", event_id="work_mon")],
                   rationale=proposal().rationale)
    out = run_one(root, scenario.scenario_id, ScriptedProvider([bad] * 4), ScriptedProvider([]))
    record = json.loads(out.read_text())
    assert record["status"] == "deferred_invalid_proposal"
    artifact = json.loads(import_result(root, out).read_text())
    assert not artifact["technical_validation"]["valid"]
    pid = artifact["proposal_id"]
    form, revision = load_review(root, "author_a", pid)
    with pytest.raises(ValueError, match="quality rejection"):
        save_review(root, "author_a", pid, {**form.model_dump(), "status": "complete",
                    "scheduling_acceptable": "yes", "autonomy_decision": "act",
                    "primary_reason": "safe", "justification": "wrong"}, revision)
    save_review(root, "author_a", pid, {**form.model_dump(), "status": "complete",
                "scheduling_acceptable": "no", "autonomy_decision": None,
                "primary_reason": "fixed event changed", "justification": "This cannot be applied"}, revision)
    assert build_rows(root)[1][0]["reason"] == "technical_validation_failed"
    packet, original, proposed, validation = preview(root, artifact)
    assert proposed is None and not validation["valid"]
    assert len(original) == len(scenario.calendar.events)


def test_v2_streamlit_navigation_and_author_isolation(imported, tmp_path):
    root, scenario = imported
    source(root)
    source(root)
    wrapper = tmp_path / "v2_ui.py"
    wrapper.write_text(f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n"
                       f"from pathlib import Path\nimport annotation_app\n"
                       f"annotation_app.ROOT = Path({str(root)!r})\nannotation_app.main()\n")
    app = AppTest.from_file(wrapper, default_timeout=10).run()
    assert not app.exception
    assert any("Política do Critic: plausibility_review_v1" in x.value for x in app.caption)
    assert any(x.label == "Proposta" for x in app.selectbox)
    first = next(x.value for x in app.selectbox if x.label == "Proposta")
    next(x for x in app.text_area if x.label == "Justificação obrigatória para concluir").set_value("Draft 1").run()
    next(x for x in app.button if x.label == "Guardar rascunho").click().run()
    assert load_review(root, "author_a", first)[0].justification == "Draft 1"
    next(x for x in app.button if x.label == "Seguinte →").click().run()
    assert not app.exception
    next(x for x in app.button if x.label == "← Anterior").click().run()
    assert not app.exception
    assert next(x.value for x in app.text_area if x.label == "Justificação obrigatória para concluir") == "Draft 1"
    app.sidebar.selectbox[0].set_value("author_b").run()
    assert not app.exception
    assert load_review(root, "author_b", first)[0].justification == ""


def test_existing_imported_scenario_proposal_and_draft_survive_ui(tmp_path):
    """Exercise the migrated real artifact through the UI on a disposable copy."""
    paths = [
        "data/benchmark_manifest.json",
        "data/scenarios/working_student_deadline_001.json",
        "data/proposals/v2p_7ab98da4402d9ddb5133850a.json",
        "data/annotations/author_a/v2p_7ab98da4402d9ddb5133850a.json",
        "eval/runs/11c42b58c5344e458f690b4b5790efa8/B_v2/working_student_deadline_001.json",
    ]
    originals = {}
    for relative in paths:
        source_path = ROOT / relative
        originals[relative] = hashlib.sha256(source_path.read_bytes()).hexdigest()
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
    assert load_manifest(tmp_path)[0]["scenario_id"] == "working_student_deadline_001"
    source = catalog(tmp_path)[0]
    pid = source["proposal_id"]
    historical_result = tmp_path / paths[-1]
    assert import_result(tmp_path, historical_result) == tmp_path / paths[2]
    assert source["scenario_id"] == "working_student_deadline_001"
    assert load_review(tmp_path, "author_a", pid)[0].status == "draft"
    wrapper = tmp_path / "existing_ui.py"
    wrapper.write_text(f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n"
                       f"from pathlib import Path\nimport annotation_app\n"
                       f"annotation_app.ROOT = Path({str(tmp_path)!r})\nannotation_app.main()\n")
    app = AppTest.from_file(wrapper, default_timeout=10).run()
    assert not app.exception
    assert next(x for x in app.selectbox if x.label == "Proposta").value == pid
    assert any("revisão de plausibilidade não disponível" in x.value for x in app.caption)
    next(x for x in app.text_area if x.label == "Justificação obrigatória para concluir").set_value("Disposable draft").run()
    next(x for x in app.button if x.label == "Guardar rascunho").click().run()
    assert load_review(tmp_path, "author_a", pid)[0].justification == "Disposable draft"
    app.sidebar.selectbox[0].set_value("author_b").run()
    assert not app.exception
    assert load_review(tmp_path, "author_b", pid)[0].justification == ""
    app.sidebar.selectbox[0].set_value("author_a").run()
    assert not app.exception
    assert load_review(tmp_path, "author_a", pid)[0].justification == "Disposable draft"
    assert all(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
               for relative, digest in originals.items())
