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
                    PlausibilityCriticEvaluation, PlausibilityReview, Proposal, Rationale,
                    UnresolvedAssumption)
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
        value = self.answers.pop(0)
        return schema.from_proposal(value) if isinstance(value, Proposal) and hasattr(schema, "from_proposal") else value


def candidate(start="2026-11-09T20:15:00+00:00"):
    return Proposal(changes=[Change(type="add", title="Assessment preparation",
                                    to_start=start, to_end="2026-11-09T21:45:00+00:00")],
                    rationale=Rationale(constraints=["work fixed"], priorities=["study"],
                                        alternatives_considered=[], summary="Study after gym."))


def review(required=False, severity="none", reason="", suggestion=""):
    return PlausibilityReview(revision_required=required, severity=severity,
                              reason=reason, suggested_improvement=suggestion)


def evaluated(scores=(4, 5, 4, 4), plausibility=None, assumptions=None):
    return CurrentCriticEvaluation(
        scores=CriticScores(reasoning=scores[0], coherence=scores[1],
                            alternatives=scores[2], clarity=scores[3]),
        weaknesses=["[plausibility] new_0 follows gym_mon"] if plausibility and plausibility.reason else [],
        feedback="Review the transition only if the user's constraints permit it.",
        plausibility_review=plausibility or review(),
        unresolved_assumptions=[] if assumptions is None else assumptions)


def unknown_facility(impact="material"):
    return UnresolvedAssumption(
        subject="gym_mon", assumption="facility is available at the moved time",
        evidence_gap="no operating hours are provided",
        potential_impact=impact, verification_source="external_source")


@pytest.fixture
def context(tmp_path):
    path = import_scenario(tmp_path, ROOT / "data/scenarios/working_student_deadline_001.json", "train")
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


def test_revised_calendar_can_resolve_old_doubt_but_trigger_new_review(context):
    first = candidate()
    shifted = Proposal(
        changes=[
            Change(type="add", title="Assessment preparation",
                   to_start="2026-11-09T18:30:00+00:00",
                   to_end="2026-11-09T20:30:00+00:00"),
            Change(type="move", event_id="gym_mon",
                   to_start="2026-11-09T21:00:00+00:00",
                   to_end="2026-11-09T22:30:00+00:00"),
        ],
        rationale=Rationale(constraints=["work fixed"], priorities=["study"],
                            alternatives_considered=[], summary="Study before gym instead."))
    assert simulate(context[1], shifted)[1]["valid"]
    old_risk = review(True, "moderate",
                      "new_0 begins shortly after gym_mon; reassess transition",
                      "Consider a workable transition")
    new_risk = review(True, "moderate",
                      "The old transition is resolved, but moving gym_mon to 21:00-22:30 "
                      "after work and study may create a new fatigue risk; facility hours are unknown",
                      "Reassess the late move and external availability without assuming it is impossible")
    result, proposer, critic = run(context, [first, shifted, first],
                                   [evaluated(plausibility=old_risk),
                                    evaluated(plausibility=new_risk), evaluated()])
    assert result["status"] == "proposal_ready" and result["refinements"] == 2
    assert result["iterations"][1]["validation"]["valid"]
    assert result["iterations"][1]["acceptance_policy"]["revision_causes"] == [
        "plausibility_revision_required"]
    assert "facility hours are unknown" in proposer.calls[2][0]
    second_packet = json.loads(critic.calls[1][0].split("\n", 1)[1])
    assert second_packet["prior_critic_reviews"][0]["result_calendar"] == result["iterations"][0]["result_calendar"]
    assert second_packet["final_calendar"] == result["iterations"][1]["result_calendar"]
    assert "two independent checks" in critic.calls[1][2]
    assert "opening hours" in critic.calls[1][2]


def test_external_dependency_is_uncertainty_not_technical_violation(context):
    shifted = Proposal(
        changes=[Change(type="move", event_id="gym_mon",
                        to_start="2026-11-09T21:00:00+00:00",
                        to_end="2026-11-09T22:30:00+00:00")],
        rationale=Rationale(constraints=["work fixed"], priorities=["exercise"],
                            alternatives_considered=[], summary="Move a flexible appointment."))
    observation = review(False, "low",
                         "Whether the facility is open at 21:00 is unknown; no conflict is visible",
                         "")
    result, _, critic = run(context, [shifted], [evaluated(plausibility=observation)])
    assert result["iterations"][0]["validation"]["valid"]
    assert result["iterations"][0]["acceptance_policy"]["accepted"]
    assert result["status"] == "proposal_ready"
    assert "unknown dependency a technical violation" in critic.calls[0][2]


@pytest.mark.parametrize("impact", ["minor", "material"])
def test_quality_acceptance_retains_relevant_unknown_without_forcing_autonomy(context, impact):
    moved = Proposal(changes=[Change(type="move", event_id="gym_mon",
                                     to_start="2026-11-09T21:00:00+00:00")],
                     rationale=candidate().rationale)
    uncertain, _, _ = run(context, [moved],
                          [evaluated(plausibility=review(False, "moderate",
                                  "External availability is unknown but further revision adds little value", ""),
                                     assumptions=[unknown_facility(impact)])])
    plain, _, _ = run(context, [moved], [evaluated()])
    assert uncertain["status"] == plain["status"] == "proposal_ready"
    assert uncertain["decision"] == plain["decision"]
    assert uncertain["iterations"][0]["validation"]["valid"]
    assert uncertain["final_unresolved_assumptions"][0]["potential_impact"] == impact
    assert uncertain["uncertainty_history"][0]["iteration"] == 0
    assert "operating hours" in unknown_facility().evidence_gap


def test_recorded_material_uncertainty_can_lead_to_one_useful_review(context):
    first = candidate()
    revised = first.model_copy(deep=True)
    revised.rationale.summary = (
        "Reconsidered the transition using the original context. No known travel or setup "
        "facts establish immediate feasibility; the schedule remains a conditional option.")
    ask = review(True, "moderate",
                 "The new study block depends on an unexamined practical transition after gym_mon; "
                 "the Proposer may find a less dependent plan or explain available context",
                 "Reconsider the transition and its alternatives using the original context")
    accepted = review(False, "low",
                      "The Proposer reconsidered the issue; no further option is supported by the "
                      "visible evidence, although practical feasibility remains unverified", "")
    result, proposer, critic = run(context, [first, revised],
                                   [evaluated(plausibility=ask, assumptions=[unknown_facility()]),
                                    evaluated(plausibility=accepted, assumptions=[unknown_facility()])])
    assert result["status"] == "proposal_ready" and result["refinements"] == 1
    assert result["iterations"][0]["acceptance_policy"]["revision_causes"] == [
        "plausibility_revision_required"]
    assert result["iterations"][1]["acceptance_policy"]["accepted"]
    assert result["iterations"][1]["operations_changed_from_previous"] is False
    assert result["iterations"][1]["rationale_changed_from_previous"] is True
    assert result["final_unresolved_assumptions"][0]["subject"] == "gym_mon"
    assert len(result["uncertainty_history"]) == 2
    assert "Unverified conditions to reassess" in proposer.calls[1][0]
    assert "Listing an uncertainty does not resolve it" in critic.calls[0][2]
    assert "An objective incompatibility is NOT required" in " ".join(critic.calls[0][2].split())
    assert "do not repeat it merely because external information is still unavailable" in " ".join(critic.calls[1][2].split())


def test_low_severity_material_impact_needs_contextual_explanation_in_prompt(context):
    result, _, critic = run(context, [candidate()],
                            [evaluated(plausibility=review(False, "low",
                                "Potential consequences are material if false, but there is no evidence "
                                "of failure and another review is unlikely to add context", ""),
                                assumptions=[unknown_facility()])])
    assert result["status"] == "proposal_ready"
    assert result["iterations"][0]["critic_evaluation"]["plausibility_review"]["severity"] == "low"
    assert result["final_unresolved_assumptions"][0]["potential_impact"] == "material"
    assert "When severity is low but an assumption's potential_impact is material" in critic.calls[0][2]


def test_prior_unknown_is_preserved_without_inferred_resolution(context):
    concern = review(True, "moderate", "new_0 may need practical transition",
                     "Reassess timing without assuming a universal buffer")
    result, proposer, critic = run(context, [candidate(), candidate("2026-11-09T21:00:00+00:00")],
                                   [evaluated(plausibility=concern, assumptions=[unknown_facility()]),
                                    evaluated()])
    assert result["status"] == "proposal_ready" and result["refinements"] == 1
    assert result["final_unresolved_assumptions"] == []
    assert result["uncertainty_history"][0]["unresolved_assumptions"][0]["subject"] == "gym_mon"
    assert result["uncertainty_history"][1]["unresolved_assumptions"] == []
    packet = json.loads(critic.calls[1][0].split("\n", 1)[1])
    assert packet["prior_critic_reviews"][0]["unresolved_assumptions"][0]["assumption"] == unknown_facility().assumption
    assert "Unverified conditions to reassess" in proposer.calls[1][0]


def test_new_contract_requires_uncertainty_list_and_old_contract_remains_readable():
    old = PlausibilityCriticEvaluation(
        scores=CriticScores(reasoning=4, coherence=4, alternatives=4, clarity=4),
        weaknesses=[], feedback="Old response", plausibility_review=review())
    assert CriticEvaluation.model_validate(old.model_dump(exclude_none=True)).unresolved_assumptions is None
    with pytest.raises(ValidationError):
        CurrentCriticEvaluation.model_validate(old.model_dump(exclude_none=True))
    assert CurrentCriticEvaluation.model_validate(
        {**old.model_dump(exclude_none=True), "unresolved_assumptions": []}).unresolved_assumptions == []
    with pytest.raises(ValidationError):
        UnresolvedAssumption(subject="gym_mon", assumption="open", evidence_gap="",
                             potential_impact="material", verification_source="external_source")


def test_importer_and_gate_features_preserve_separation(context):
    from gate_dataset_v2 import features
    root, source = context
    path = run_b(root, source.scenario_id, ScriptedProvider([candidate()]),
                 ScriptedProvider([evaluated(assumptions=[unknown_facility()])]))
    record = json.loads(path.read_text())
    artifact = json.loads(import_result(root, path).read_text())
    assert artifact["final_unresolved_assumptions"] == record["final_unresolved_assumptions"]
    assert artifact["uncertainty_history"] == record["uncertainty_history"]
    predictors = features(source, candidate(), artifact["critic_score"])
    assert not any("assumption" in key or "verification" in key for key in predictors)
    record["iterations"][0]["critic_evaluation"].pop("unresolved_assumptions")
    altered = root / "tampered_uncertainty.json"
    altered.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="invalid Critic evaluation"):
        import_result(root, altered)
    record = json.loads(path.read_text())
    record["final_unresolved_assumptions"] = []
    altered.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="final uncertainty summary"):
        import_result(root, altered)


def test_real_historical_v1_run_imports_without_backfilled_uncertainties(context):
    path = ROOT / "eval/runs/de85af3de5724c3baaeacfe8a7d0de1e/B/working_student_deadline_001.json"
    if not path.exists():
        pytest.skip("local historical run is not checked into the repository")
    before = path.read_bytes()
    artifact = json.loads(import_result(context[0], path).read_text())
    assert artifact["critic_policy_version"] == "plausibility_review_v1"
    assert "final_unresolved_assumptions" not in artifact
    assert "uncertainty_history" not in artifact
    assert path.read_bytes() == before


def test_streamlit_displays_new_uncertainty_without_claiming_execution(context, tmp_path):
    root, source = context
    path = run_b(root, source.scenario_id, ScriptedProvider([candidate()]),
                 ScriptedProvider([evaluated(assumptions=[unknown_facility()])]))
    import_result(root, path)
    wrapper = tmp_path / "uncertainty_ui.py"
    wrapper.write_text(f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n"
                       f"from pathlib import Path\nimport annotation_app\n"
                       f"annotation_app.ROOT = Path({str(root)!r})\nannotation_app.main()\n")
    app = AppTest.from_file(wrapper, default_timeout=10).run()
    assert not app.exception
    assert not any("não garante viabilidade externa" in item.value for item in app.caption)
    diagnostic = tmp_path / "uncertainty_diagnostic.py"
    diagnostic.write_text(
        f"import json, sys\nsys.path.insert(0, {str(ROOT)!r})\n"
        f"import annotation_app, streamlit as st\n"
        f"record = json.load(open({str(path)!r}))\n"
        "annotation_app._critic_history(record)\n"
        "st.write('Incertezas finais B:', record.get('final_unresolved_assumptions'))\n")
    diagnostic_app = AppTest.from_file(diagnostic, default_timeout=10).run()
    assert not diagnostic_app.exception
    assert any(item.label == "Iteração 0" for item in diagnostic_app.expander)
    assert any("Incertezas finais B:" in item.value for item in diagnostic_app.markdown)


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
    assert b["prompt_versions"]["proposer_wire_schema_version"] == "compact_proposal_v1"
    assert (b["prompt_versions"]["proposer_wire_schema_sha256"] ==
            a["prompt_versions"]["proposer_wire_schema_sha256"])
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
    assert not any(f"Política do Critic: {CRITIC_POLICY_VERSION}" in x.value for x in app.caption)
    diagnostic = tmp_path / "review_diagnostic.py"
    diagnostic.write_text(
        f"import json, sys\nsys.path.insert(0, {str(ROOT)!r})\n"
        f"import annotation_app, streamlit as st\n"
        f"record = json.load(open({str(path)!r}))\n"
        "st.caption('Política do Critic: ' + record['critic_policy_version'])\n"
        "annotation_app._critic_history(record)\n")
    diagnostic_app = AppTest.from_file(diagnostic, default_timeout=10).run()
    assert not diagnostic_app.exception
    assert any(f"Política do Critic: {CRITIC_POLICY_VERSION}" in x.value
               for x in diagnostic_app.caption)
    assert len(diagnostic_app.expander) == 2
