"""Benchmark, anotação independente e checks objetivos sem chamadas IAedu."""
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))

import make_benchmark  # noqa: E402
from annotation_workflow import (ProposalAdjudication, ProposalAnnotation,
                                 ScenarioAdjudication, ScenarioAnnotation,
                                 cohens_kappa, compare, prepare_adjudications,
                                 prepare_proposals, prepare_scenarios,
                                 validate_adjudications)  # noqa: E402
from benchmark import grouped_train_folds, validate_benchmark  # noqa: E402
from compare_runs import collect  # noqa: E402
from gate_dataset import build_rows, grouped_gate_folds  # noqa: E402
from models import Change, Profile, Proposal, Rationale, Scenario  # noqa: E402
from proposal_catalog import import_result, load_sources  # noqa: E402
from quality_checks import evaluate_proposal  # noqa: E402


@pytest.fixture
def benchmark_root(tmp_path):
    (tmp_path / "data").mkdir()
    shutil.copy(ROOT / "data" / "profile.json", tmp_path / "data" / "profile.json")
    shutil.copy(ROOT / "data" / "benchmark_manifest.json",
                tmp_path / "data" / "benchmark_manifest.json")
    shutil.copytree(ROOT / "data" / "scenarios", tmp_path / "data" / "scenarios")
    return tmp_path


def test_generator_preserves_originals_and_factor_variation(tmp_path, monkeypatch):
    out = tmp_path / "data" / "scenarios"
    monkeypatch.setattr(make_benchmark, "OUT", out)
    monkeypatch.setattr(make_benchmark, "MANIFEST", tmp_path / "data" / "benchmark_manifest.json")
    assert make_benchmark.generate() == (20, 41)
    for seed in make_benchmark.SEEDS:
        generated = json.loads((out / f"{seed.id}.json").read_text())
        original = json.loads((ROOT / "data" / "scenarios" / f"{seed.id}.json").read_text())
        assert generated == original
    assert all(s.reference_decision is None and not s.annotations
               for s in make_benchmark.scenarios)
    assert len(list(out.glob("*.json"))) == 41


def test_manifest_split_and_grouped_folds(benchmark_root):
    errors, rows = validate_benchmark(benchmark_root)
    assert errors == []
    assert len(rows) == 41
    folds = grouped_train_folds(rows, 3)
    final_test_ids = {r["scenario_id"] for r in rows if r["split"] == "test"}
    train_ids = {r["scenario_id"] for r in rows if r["split"] == "train"}
    assert len(folds) == 3
    assert set().union(*(set(f["validation_ids"]) for f in folds)) == train_ids
    for fold in folds:
        assert not (set(fold["train_ids"]) & set(fold["validation_ids"]))
        assert not ((set(fold["train_ids"]) | set(fold["validation_ids"])) & final_test_ids)
        train_families = {r["family"] for r in rows if r["scenario_id"] in fold["train_ids"]}
        validation_families = {r["family"] for r in rows if r["scenario_id"] in fold["validation_ids"]}
        assert not (train_families & validation_families)


def test_validator_detects_family_leakage(benchmark_root):
    manifest_path = benchmark_root / "data" / "benchmark_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    row = next(r for r in manifest["scenarios"] if r["scenario_id"] == "hard_class_02")
    row["split"] = "test"
    manifest_path.write_text(json.dumps(manifest))
    path = benchmark_root / "data" / "scenarios" / "hard_class_02.json"
    scenario = json.loads(path.read_text())
    scenario["split"] = "test"
    path.write_text(json.dumps(scenario))
    errors, _ = validate_benchmark(benchmark_root)
    assert any("família em treino e teste" in error for error in errors)


def _synthetic_result(root):
    proposal = Proposal(changes=[Change(type="move", event_id="gym_wed",
                                        to_start="2026-11-11T20:00")],
                        rationale=Rationale(constraints=["fixed class"],
                                            priorities=["deadline"],
                                            alternatives_considered=[], summary="Move gym."))
    path = root / "eval" / "runs" / "synthetic_run" / "B" / "soft_gym_01.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"configuration": "B", "status": "proposal_ready",
                                "critic_accepted": True, "final_score": 4.25,
                                "scenario_id": "soft_gym_01", "family": "soft_gym_deadline",
                                "split": "train", "run_id": "synthetic_run",
                                "proposer_provider": "iaedu", "proposer_model": "synthetic",
                                "critic_provider": "iaedu", "critic_model": "synthetic",
                                "final_proposal": proposal.model_dump(),
                                "iterations": [{"index": 0, "proposal": proposal.model_dump(),
                                                "critic_evaluation": {"overall": 4.25}}]}))
    return path


def _complete_scenario(root, author, sid):
    path = root / "data" / "annotation_work" / author / "scenario" / "forms" / f"{sid}.json"
    form = ScenarioAnnotation.model_validate_json(path.read_text())
    form.status = "complete"
    form.acceptable_outcomes = ["Preservar compromissos fixos e encontrar horário livre."]
    form.hard_constraints = ["Não mover aulas fixas."]
    form.impact_factors = ["Prazo próximo."]
    form.ambiguity_present = False
    path.write_text(form.model_dump_json(indent=2))


def _complete_proposal(root, author, pid, decision):
    path = root / "data" / "annotation_work" / author / "proposal" / "forms" / f"{pid}.json"
    form = ProposalAnnotation.model_validate_json(path.read_text())
    form.status = "complete"
    form.decision = decision
    form.decision_rationale = "Decisão relativa a esta proposta concreta."
    form.scheduling_acceptable = True
    form.intervention_impact = 2
    form.intervention_risk = 2
    if decision == "defer":
        form.defer_reason_primary = "confirmation_required"
    path.write_text(form.model_dump_json(indent=2))


def test_two_phase_blinding_adjudication_and_gate_dataset(benchmark_root):
    result_path = _synthetic_result(benchmark_root)
    source_path = import_result(benchmark_root, result_path)
    assert import_result(benchmark_root, result_path) == source_path
    source = load_sources(benchmark_root)[0]
    pid = source["proposal_id"]
    assert source["refinement_history"] and source["scenario_id"] == "soft_gym_01"
    for author in ("author_a", "author_b"):
        assert prepare_scenarios(benchmark_root, author) == 41
    base = benchmark_root / "data" / "annotation_work" / "author_a"
    scenario_packet = json.loads((base / "scenario" / "packets" / "soft_gym_01.json").read_text())
    assert "decision" not in ScenarioAnnotation.model_fields
    assert "draft_label" not in json.dumps(scenario_packet)
    with pytest.raises(ValueError):
        prepare_proposals(benchmark_root, "author_a")
    with pytest.raises(ValueError):
        ScenarioAnnotation(scenario_id="x", annotator_id="author_a", status="complete")
    with pytest.raises(ValueError):
        build_rows(benchmark_root)  # nenhuma anotação humana completa

    for author in ("author_a", "author_b"):
        _complete_scenario(benchmark_root, author, "soft_gym_01")
    assert compare(benchmark_root, "scenario", "author_a", "author_b")["complete_pairs"] == 1
    assert prepare_adjudications(benchmark_root, "scenario", "author_a", "author_b") == 1
    scenario_path = (benchmark_root / "data" / "annotation_work" / "adjudications"
                     / "scenario" / "soft_gym_01.json")
    sa = ScenarioAdjudication.model_validate_json(scenario_path.read_text())
    sa.status = "complete"
    sa.acceptable_outcomes = ["Preservar compromissos fixos e encontrar horário livre."]
    sa.ambiguity_present = False
    sa.resolution_rationale = "Acordo dos dois autores."
    sa.resolved_by = ["author_a", "author_b"]
    scenario_path.write_text(sa.model_dump_json())

    for author in ("author_a", "author_b"):
        assert prepare_proposals(benchmark_root, author) == 1
    proposal_packet = json.loads((base / "proposal" / "packets" / f"{pid}.json").read_text())
    assert set(proposal_packet) == {"proposal_id", "scenario", "scenario_reference", "final_proposal"}
    for hidden in ("critic_score", "critic_evaluation", "refinement_history",
                   "decision", "split", "family", "model", "configuration"):
        assert hidden not in json.dumps(proposal_packet)
    assert "changes" in proposal_packet["final_proposal"]
    assert "rationale" in proposal_packet["final_proposal"]
    assert proposal_packet["scenario_reference"]["acceptable_outcomes"]
    with pytest.raises(ValueError):
        ProposalAnnotation(proposal_id=pid, scenario_id="soft_gym_01",
                           annotator_id="author_a", status="complete")
    with pytest.raises(ValueError):
        ProposalAnnotation(proposal_id=pid, scenario_id="soft_gym_01",
                           annotator_id="author_a", status="complete", decision="act",
                           decision_rationale="Synthetic", scheduling_acceptable=False,
                           intervention_impact=2, intervention_risk=2)
    _complete_proposal(benchmark_root, "author_a", pid, "act")
    _complete_proposal(benchmark_root, "author_b", pid, "defer")
    report = compare(benchmark_root, "proposal", "author_a", "author_b")
    assert report["complete_pairs"] == 1
    assert report["decision_disagreements"] == [pid]
    assert prepare_adjudications(benchmark_root, "proposal", "author_a", "author_b") == 1
    assert validate_adjudications(benchmark_root, "proposal", "author_a", "author_b")["pending"] == [pid]
    proposal_path = (benchmark_root / "data" / "annotation_work" / "adjudications"
                     / "proposal" / f"{pid}.json")
    pa = ProposalAdjudication.model_validate_json(proposal_path.read_text())
    pa.status = "complete"
    pa.final_decision = "defer"
    pa.decision_rationale = "Risco considerado alto após discussão."
    pa.scheduling_acceptable = True
    pa.intervention_impact = 2
    pa.intervention_risk = 4
    pa.defer_reason_primary = "high_impact"
    pa.resolved_by = ["author_a", "author_b"]
    proposal_path.write_text(pa.model_dump_json())
    rows = build_rows(benchmark_root)
    assert len(rows) == 1 and rows[0]["label"] == "defer"
    assert rows[0]["label_source"] == "proposal_adjudication"
    assert rows[0]["base_id"] == "soft_gym"
    assert not {"scenario_id", "proposal_id", "family", "split", "base_id", "label"} & set(rows[0]["features"])
    with pytest.raises(ValueError):
        build_rows(benchmark_root, split="test")


def test_kappa_when_applicable():
    assert cohens_kappa([("act", "act"), ("act", "act")]) is None
    assert cohens_kappa([("act", "act"), ("act", "defer"),
                         ("defer", "defer"), ("defer", "defer")]) == 0.5


def test_proposals_from_same_base_stay_in_one_fold():
    rows = [
        {"proposal_id": "p1", "base_id": "b1", "family": "f1", "split": "train"},
        {"proposal_id": "p2", "base_id": "b1", "family": "f1", "split": "train"},
        {"proposal_id": "p3", "base_id": "b2", "family": "f2", "split": "train"},
        {"proposal_id": "p4", "base_id": "b3", "family": "f3", "split": "train"},
    ]
    folds = grouped_gate_folds(rows)
    assert len(folds) == 3
    assert all(({"p1", "p2"} <= set(fold["validation_proposal_ids"]))
               or ({"p1", "p2"} <= set(fold["train_proposal_ids"])) for fold in folds)
    with pytest.raises(ValueError):
        grouped_gate_folds(rows + [{"proposal_id": "px", "base_id": "bx",
                                   "family": "fx", "split": "test"}])


def test_catalog_rejects_unaccepted_b_result(benchmark_root):
    path = _synthetic_result(benchmark_root)
    record = json.loads(path.read_text())
    record["status"] = "deferred_critic_threshold"
    record["critic_accepted"] = False
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        import_result(benchmark_root, path)


def test_objective_checks_keep_quality_dimensions_separate():
    profile = Profile.model_validate_json((ROOT / "data" / "profile.json").read_text())
    scenario = Scenario.model_validate_json((ROOT / "data" / "scenarios" / "hard_class_01.json").read_text())
    check = json.loads((ROOT / "data" / "objective_checks.json").read_text())["scenarios"][scenario.id]
    rationale = Rationale(constraints=[], priorities=[], alternatives_considered=[], summary="synthetic")
    good = Proposal(changes=[Change(type="add", title="Project partner call",
                                    to_start="2026-11-11T08:00", to_end="2026-11-11T09:00")],
                    rationale=rationale)
    quality = evaluate_proposal(scenario, profile, good.model_dump(), check)
    assert quality["structural"]["status"] == "pass"
    assert quality["constraints"]["status"] == "pass"
    assert quality["request_satisfaction"]["status"] == "partial_conditions_pass"
    assert quality["rationale_quality"]["status"] == "not_assessed"
    assert quality["autonomy_appropriateness"]["status"] == "not_assessed"
    assert evaluate_proposal(scenario, profile, {"changes": [{"type": "add"}],
                                                 "rationale": rationale.model_dump()}, check)["structural"]["status"] == "fail"
    bad = Proposal(changes=[Change(type="add", title="Call",
                                   to_start="2026-11-11T10:30", to_end="2026-11-11T11:30")],
                   rationale=rationale)
    assert evaluate_proposal(scenario, profile, bad.model_dump(), check)["constraints"]["status"] == "fail"
    assert evaluate_proposal(scenario, profile, good.model_dump())["request_satisfaction"]["status"] == "unknown"
    empty = Proposal(changes=[], rationale=rationale)
    assert evaluate_proposal(scenario, profile, empty.model_dump(), check)["applicability"]["status"] == "fail"


def test_a_b_run_pairing_without_api(tmp_path):
    a = tmp_path / "runa" / "A"
    b = tmp_path / "runb" / "B"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    a.joinpath("x.json").write_text(json.dumps({"experiment_id": "pilot", "scenario_id": "x",
                                               "configuration": "A", "repeat_index": 0,
                                               "provider": "iaedu", "model": "GPT-5.5",
                                               "decision": "act", "proposal": {"changes": []}}))
    b.joinpath("x.json").write_text(json.dumps({"experiment_id": "pilot", "scenario_id": "x",
                                               "configuration": "B", "repeat_index": 0,
                                               "proposer_provider": "iaedu", "proposer_model": "GPT-5.5",
                                               "decision": "defer", "final_proposal": {"changes": []}}))
    rows = collect(tmp_path, "pilot")
    assert len(rows) == 1 and rows[0]["paired"] and rows[0]["same_proposer_model"]
