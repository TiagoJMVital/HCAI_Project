"""Local UI adapter tests use temporary synthetic files, never real annotations/API."""
import json
import shutil
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from annotation_ui import (  # noqa: E402
    comparison, items, load_adjudication, load_item, load_pair, paired_ids,
    prepare, save_adjudication, save_form,
)
from annotation_workflow import (ProposalAnnotation, ProposalAdjudication,
                                 ScenarioAnnotation, ScenarioAdjudication)  # noqa: E402
from gate_dataset import build_rows  # noqa: E402
from models import Change, Proposal, Rationale  # noqa: E402
from proposal_catalog import import_result  # noqa: E402


@pytest.fixture
def local_root(tmp_path):
    (tmp_path / "data").mkdir()
    for name in ("profile.json", "benchmark_manifest.json"):
        shutil.copy(ROOT / "data" / name, tmp_path / "data" / name)
    shutil.copytree(ROOT / "data" / "scenarios", tmp_path / "data" / "scenarios")
    return tmp_path


def _source(root):
    proposal = Proposal(changes=[Change(type="move", event_id="gym_wed",
                                        to_start="2026-11-11T20:00")],
                        rationale=Rationale(constraints=["keep fixed events"],
                                            priorities=["deadline"],
                                            alternatives_considered=[], summary="Move gym."))
    path = root / "eval" / "runs" / "ui_test" / "B" / "soft_gym_01.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"configuration": "B", "status": "proposal_ready",
                                "critic_accepted": True, "final_score": 4.25,
                                "scenario_id": "soft_gym_01", "family": "soft_gym_deadline",
                                "split": "train", "run_id": "ui_test",
                                "proposer_provider": "iaedu", "proposer_model": "synthetic",
                                "critic_provider": "iaedu", "critic_model": "synthetic",
                                "decision": "defer", "draft_label": "defer",
                                "final_proposal": proposal.model_dump(),
                                "iterations": [{"proposal": proposal.model_dump(),
                                                "critic_evaluation": {"overall": 4.25}}]}))
    return import_result(root, path).stem


def _completed_scenario(root, author):
    _, form, digest = load_item(root, author, "scenario", "soft_gym_01")
    form.update(status="complete", acceptable_outcomes=["Preserve fixed class and find free time"],
                hard_constraints=["Do not move fixed class"],
                impact_factors=["Deadline"], ambiguity_present=False)
    save_form(root, author, "scenario", "soft_gym_01", form, digest)


def _adjudicate_scenario(root):
    form, digest = load_adjudication(root, "scenario", "soft_gym_01")
    form.update(status="complete", acceptable_outcomes=["Preserve fixed class and find free time"],
                hard_constraints=["Do not move fixed class"],
                impact_factors=["Deadline"], ambiguity_present=False,
                resolution_rationale="Both authors agreed after reviewing alternatives",
                resolved_by=["author_a", "author_b"])
    save_adjudication(root, "scenario", "soft_gym_01", form, digest)


def test_scenario_loading_drafts_validation_and_author_isolation(local_root):
    assert prepare(local_root, "author_a", "scenario") == 41
    assert prepare(local_root, "author_b", "scenario") == 41
    assert len(items(local_root, "author_a", "scenario")) == 41
    packet, form, digest = load_item(local_root, "author_a", "scenario", "amb_health_01")
    assert packet["scenario_id"] == "amb_health_01"
    assert packet["calendar"] and packet["profile"]["priorities"]
    assert "draft_label" not in packet and "split" not in packet
    raw_path = local_root / "data" / "annotation_work" / "author_a" / "scenario" / "forms" / "amb_health_01.json"
    old_b = (local_root / "data" / "annotation_work" / "author_b" / "scenario" / "forms" / "amb_health_01.json").read_bytes()
    form["impact_factors"] = ["May affect personal routine"]
    revision = save_form(local_root, "author_a", "scenario", "amb_health_01", form, digest)
    assert revision != digest
    assert next(x for x in items(local_root, "author_a", "scenario")
                if x["id"] == "amb_health_01")["state"] == "draft"
    assert (local_root / "data" / "annotation_work" / "author_b" / "scenario" / "forms" / "amb_health_01.json").read_bytes() == old_b
    with pytest.raises(ValueError, match="mudou"):
        save_form(local_root, "author_a", "scenario", "amb_health_01", form, digest)
    form["status"] = "complete"
    with pytest.raises(ValueError, match="cenário completo"):
        save_form(local_root, "author_a", "scenario", "amb_health_01", form, revision)
    assert json.loads(raw_path.read_text())["status"] == "draft"
    assert not list(raw_path.parent.glob("*.tmp"))
    with pytest.raises(ValueError, match="avaliador desconhecido"):
        prepare(local_root, "outsider", "scenario")
    form["status"] = "draft"
    with pytest.raises(ValueError, match="avaliador"):
        save_form(local_root, "author_b", "scenario", "amb_health_01", form,
                  load_item(local_root, "author_b", "scenario", "amb_health_01")[2])


def test_proposal_blinding_blocking_and_defer_reasons(local_root):
    pid = _source(local_root)
    for author in ("author_a", "author_b"):
        prepare(local_root, author, "scenario")
    with pytest.raises(ValueError, match="adjudicar"):
        prepare(local_root, "author_a", "proposal")
    with pytest.raises(ValueError, match="ambos"):
        comparison(local_root, "scenario")
    _completed_scenario(local_root, "author_a")
    with pytest.raises(ValueError):
        load_pair(local_root, "scenario", "soft_gym_01")
    _completed_scenario(local_root, "author_b")
    assert paired_ids(local_root, "scenario") == ["soft_gym_01"]
    assert comparison(local_root, "scenario")["complete_pairs"] == 1
    _adjudicate_scenario(local_root)
    _, completed, revision = load_item(local_root, "author_a", "scenario", "soft_gym_01")
    with pytest.raises(ValueError, match="adjudicado"):
        save_form(local_root, "author_a", "scenario", "soft_gym_01",
                  {**completed, "impact_factors": ["Changed after consensus"]},
                  revision, confirm_completed=True)
    for author in ("author_a", "author_b"):
        assert prepare(local_root, author, "proposal") == 1
    packet, form, digest = load_item(local_root, "author_a", "proposal", pid)
    assert packet["final_proposal"]["changes"]
    assert packet["scenario_reference"]["acceptable_outcomes"]
    for hidden in ("critic_score", "critic_evaluation", "refinement_history",
                   "decision", "draft_label", "split", "family", "model"):
        assert hidden not in json.dumps(packet)
    packet_path = local_root / "data" / "annotation_work" / "author_a" / "proposal" / "packets" / f"{pid}.json"
    raw = json.loads(packet_path.read_text())
    raw["critic_score"] = 5
    raw["decision"] = "act"
    packet_path.write_text(json.dumps(raw))
    safe, _, _ = load_item(local_root, "author_a", "proposal", pid)
    assert "critic_score" not in safe and "decision" not in safe
    form.update(status="complete", decision="act", decision_rationale="Synthetic test",
                scheduling_acceptable=False, intervention_impact=2, intervention_risk=2,
                annotation_version=2)
    with pytest.raises(ValueError, match="act exige"):
        save_form(local_root, "author_a", "proposal", pid, form, digest)
    form["decision"] = "defer"
    form["defer_reason_primary"] = None
    with pytest.raises(ValueError, match="motivo principal"):
        save_form(local_root, "author_a", "proposal", pid, form, digest)
    form["defer_reason_primary"] = "clarification_required"
    form["clarification_question"] = "Which event may be moved?"
    save_form(local_root, "author_a", "proposal", pid, form, digest)
    _, saved, _ = load_item(local_root, "author_a", "proposal", pid)
    assert saved["defer_reason_primary"] == "clarification_required"
    assert saved["clarification_question"] == "Which event may be moved?"
    with pytest.raises(ValueError, match="confirmação"):
        save_form(local_root, "author_a", "proposal", pid,
                  {**saved, "decision_rationale": "Changed"},
                  load_item(local_root, "author_a", "proposal", pid)[2])


def test_comparison_adjudication_legacy_compatibility_and_no_feature_leak(local_root):
    pid = _source(local_root)
    for author in ("author_a", "author_b"):
        prepare(local_root, author, "scenario")
        _completed_scenario(local_root, author)
    _adjudicate_scenario(local_root)
    for author in ("author_a", "author_b"):
        prepare(local_root, author, "proposal")
    with pytest.raises(ValueError):
        comparison(local_root, "proposal")
    for author, decision in (("author_a", "act"), ("author_b", "defer")):
        _, form, digest = load_item(local_root, author, "proposal", pid)
        form.update(status="complete", decision=decision,
                    decision_rationale="Synthetic test label",
                    scheduling_acceptable=True, intervention_impact=2,
                    intervention_risk=2, annotation_version=2)
        if decision == "defer":
            form["defer_reason_primary"] = "third_party_impact"
        save_form(local_root, author, "proposal", pid, form, digest)
    report = comparison(local_root, "proposal")
    assert report["complete_pairs"] == 1
    assert report["decision_disagreements"] == [pid]
    assert report["observed_agreement"] == 0
    assert "unpaired_complete" not in report
    pair = load_pair(local_root, "proposal", pid)
    assert pair[0]["decision"] == "act" and pair[1]["decision"] == "defer"
    consensus, digest = load_adjudication(local_root, "proposal", pid)
    consensus.update(status="complete", final_decision="defer",
                     decision_rationale="Agreed after discussion",
                     scheduling_acceptable=True, intervention_impact=2,
                     intervention_risk=3, resolved_by=["author_a", "author_b"])
    with pytest.raises(ValueError, match="motivo principal"):
        save_adjudication(local_root, "proposal", pid, consensus, digest)
    consensus["defer_reason_primary"] = "confirmation_required"
    save_adjudication(local_root, "proposal", pid, consensus, digest)
    rows = build_rows(local_root)
    assert len(rows) == 1 and rows[0]["label"] == "defer"
    assert not any("defer_reason" in key or "clarification" in key for key in rows[0]["features"])
    assert "defer_reason_primary" not in rows[0]
    historic = {"proposal_id": "old", "scenario_id": "old", "annotator_id": "author_a",
                "status": "complete", "decision": "defer", "decision_rationale": "Historical",
                "scheduling_acceptable": True, "intervention_impact": 2,
                "intervention_risk": 2}
    assert ProposalAnnotation.model_validate(historic).annotation_version == 1
    historic_adj = {"proposal_id": "old", "scenario_id": "old",
                    "annotator_ids": ["author_a", "author_b"], "status": "complete",
                    "final_decision": "defer", "decision_rationale": "Historical",
                    "scheduling_acceptable": True, "intervention_impact": 2,
                    "intervention_risk": 2, "resolved_by": ["author_a", "author_b"]}
    assert ProposalAdjudication.model_validate(historic_adj).annotation_version == 1


def test_version_two_reason_rules_are_explanatory_only():
    base = {"proposal_id": "p", "scenario_id": "s", "annotator_id": "author_a",
            "status": "complete", "decision": "defer",
            "decision_rationale": "Synthetic test", "scheduling_acceptable": True,
            "intervention_impact": 2, "intervention_risk": 2,
            "annotation_version": 2, "defer_reason_primary": "high_impact"}
    assert ProposalAnnotation.model_validate(base).defer_reason_primary == "high_impact"
    with pytest.raises(ValueError, match="motivos de deferimento repetidos"):
        ProposalAnnotation.model_validate({**base, "defer_reason_additional": ["high_impact"]})
    with pytest.raises(ValueError, match="pergunta de esclarecimento"):
        ProposalAnnotation.model_validate({**base, "clarification_question": "What changed?"})
    with pytest.raises(ValueError, match="motivos de deferimento só"):
        ProposalAnnotation.model_validate({**base, "decision": "act"})


def test_streamlit_pages_open_with_temporary_benchmark(local_root, tmp_path):
    _source(local_root)
    wrapper = tmp_path / "ui_smoke.py"
    wrapper.write_text(
        f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n"
        f"from pathlib import Path\nimport annotation_app\n"
        f"annotation_app.ROOT = Path({str(local_root)!r})\n"
        "annotation_app.main()\n"
    )
    app = AppTest.from_file(wrapper, default_timeout=10).run()
    assert not app.exception
    assert app.header[0].value == "Fase A · Cenários"
    assert any("09/11/2026" in button.label for button in app.button)
    next_week = next(button for button in app.button if button.label == "Semana seguinte →")
    next_week.click().run()
    assert not app.exception
    assert any("16/11/2026" in button.label for button in app.button)
    app.sidebar.radio[0].set_value("Propostas").run()
    assert not app.exception
    assert any("fase B só fica disponível" in item.value for item in app.info)
    app.sidebar.radio[0].set_value("Comparação e adjudicação").run()
    assert not app.exception
    assert any("respostas individuais permanecem ocultas" in item.value for item in app.info)
    app.sidebar.radio[0].set_value("Guia de autonomia").run()
    assert not app.exception
    assert app.header[0].value == "Guia preliminar de autonomia"


def test_navigation_after_draft_save_and_author_switch(local_root, tmp_path):
    """Reproduces the former StreamlitWidgetAlreadyInstantiatedError."""
    wrapper = tmp_path / "navigation_repro.py"
    wrapper.write_text(
        f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n"
        "from pathlib import Path\nimport annotation_app\n"
        f"annotation_app.ROOT = Path({str(local_root)!r})\n"
        "annotation_app.main()\n"
    )
    app = AppTest.from_file(wrapper, default_timeout=10).run()
    assert next(x.value for x in app.selectbox if x.label == "Cenário") == "amb_health_01"
    next(x for x in app.text_area if x.label == "Notas sobre ambiguidade").set_value(
        "Rascunho temporário de teste").run()
    next(x for x in app.button if x.label == "Guardar rascunho").click().run()
    saved_path = local_root / "data/annotation_work/author_a/scenario/forms/amb_health_01.json"
    saved_bytes = saved_path.read_bytes()
    assert json.loads(saved_bytes)["ambiguity_notes"] == "Rascunho temporário de teste"

    for expected in ("amb_health_02", "amb_super_01"):
        next(x for x in app.button if x.label == "Seguinte →").click().run()
        assert not app.exception
        assert next(x.value for x in app.selectbox if x.label == "Cenário") == expected
    next(x for x in app.button if x.label == "← Anterior").click().run()
    assert not app.exception
    assert next(x.value for x in app.selectbox if x.label == "Cenário") == "amb_health_02"
    next(x for x in app.button if x.label == "← Anterior").click().run()
    assert not app.exception
    assert next(x.value for x in app.selectbox if x.label == "Cenário") == "amb_health_01"
    assert next(x.value for x in app.text_area if x.label == "Notas sobre ambiguidade") == "Rascunho temporário de teste"
    next(x for x in app.selectbox if x.label == "Cenário").set_value("soft_gym_01").run()
    assert not app.exception
    assert next(x.value for x in app.selectbox if x.label == "Cenário") == "soft_gym_01"

    app.sidebar.selectbox[0].set_value("author_b").run()
    assert not app.exception
    assert next(x.value for x in app.selectbox if x.label == "Cenário") == "amb_health_01"
    assert next(x.value for x in app.text_area if x.label == "Notas sobre ambiguidade") == ""
    next(x for x in app.button if x.label == "Seguinte →").click().run()
    assert not app.exception
    app.sidebar.selectbox[0].set_value("author_a").run()
    assert not app.exception
    next(x for x in app.selectbox if x.label == "Cenário").set_value("amb_health_01").run()
    assert next(x.value for x in app.text_area if x.label == "Notas sobre ambiguidade") == "Rascunho temporário de teste"
    assert saved_path.read_bytes() == saved_bytes
    assert json.loads(saved_path.read_text())["status"] == "draft"
