"""Local checks for schema-2 sidecars, final-state duration and no-op safety."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from benchmark_v2 import import_scenario
from calendar_v2 import simulate
from models import Change, Proposal, Rationale
from rules import rule_based_decision
from scenario_v2 import (ConfirmedEventChange, DurationRequirement, V2HardConstraint,
                         V2Scenario, load_scenario, load_manifest)


def scenario(events):
    return V2Scenario.model_validate({
        "schema_version": "2.0", "scenario_id": "aggregate_case", "family_id": "test_family",
        "profile": {"profile_id": "p", "description": "test", "timezone": "Europe/Lisbon",
                    "priorities": {"work": 3}, "hard_constraints": [], "soft_preferences": [],
                    "autonomy_preferences": {"allow_create_in_free_slots": True,
                     "allow_move_personal_flexible_events": True,
                     "require_confirmation_for_third_party_changes": True,
                     "require_confirmation_for_health_appointments": True,
                     "require_confirmation_for_high_impact_changes": True}},
        "now": "2027-03-29T08:00:00+01:00", "calendar": {"events": events},
        "user_request": "Keep two hours of work."})


def event(eid, start, end, *, fixed=False):
    return {"id": eid, "title": eid, "start": start, "end": end,
            "category": "work", "importance": 3, "fixed": fixed,
            "participants": ["user"], "description": ""}


def proposal(*changes):
    return Proposal(changes=list(changes), rationale=Rationale(
        constraints=["two hours"], priorities=[], alternatives_considered=[],
        summary="Existing schedule already covers the request."))


def attach(s, *, minutes=120, complete=True):
    s._aggregate_requirements = [DurationRequirement.model_validate({
        "id": "weekly_work", "kind": "minimum_duration", "event_category": "work",
        "start": "2027-03-29T00:00:00+01:00", "end": "2027-03-30T00:00:00+01:00",
        "minimum_minutes": minutes, "complete_horizon": complete})]
    return s


def test_noop_is_structural_but_not_autonomous():
    s = scenario([event("work", "2027-03-29T09:00:00+01:00", "2027-03-29T11:00:00+01:00")])
    p = proposal()
    result, report = simulate(s, p)
    assert report["valid"] and report["no_op"] and result == s.calendar.events
    assert rule_based_decision(p, s.calendar.events, [])[0] == "defer"
    assert not simulate(attach(s, minutes=180), p)[1]["valid"]


def test_final_duration_move_add_delete_and_unknown():
    s = attach(scenario([event("a", "2027-03-29T09:00:00+01:00", "2027-03-29T10:00:00+01:00"),
                         event("b", "2027-03-29T10:00:00+01:00", "2027-03-29T11:00:00+01:00")]))
    assert simulate(s, proposal(Change(type="move", event_id="a", to_start="2027-03-29T12:00:00+01:00")))[1]["aggregate_checks"][0]["status"] == "pass"
    assert simulate(s, proposal(Change(type="delete", event_id="a")))[1]["aggregate_checks"][0]["status"] == "fail"
    untyped = proposal(Change(type="delete", event_id="a"), Change(type="add", title="work?",
                       to_start="2027-03-29T12:00:00+01:00"))
    assert simulate(s, untyped)[1]["aggregate_checks"][0]["status"] == "unknown"
    typed = proposal(Change(type="delete", event_id="a"), Change(type="add", title="work",
                     category="work", to_start="2027-03-29T12:00:00+01:00"))
    assert simulate(s, typed)[1]["aggregate_checks"][0]["status"] == "pass"
    assert simulate(attach(s.model_copy(deep=True), complete=False), typed)[1]["aggregate_checks"][0]["status"] == "unknown"


def test_overlaps_not_double_counted_and_fixed_still_protected():
    s = attach(scenario([event("a", "2027-03-29T09:00:00+01:00", "2027-03-29T10:30:00+01:00", fixed=True),
                         event("b", "2027-03-29T10:00:00+01:00", "2027-03-29T11:30:00+01:00")]), minutes=180)
    report = simulate(s, proposal())[1]
    assert report["aggregate_checks"][0]["minutes"] == 150
    assert report["aggregate_checks"][0]["status"] == "fail"
    bad = simulate(s, proposal(Change(type="move", event_id="a", to_start="2027-03-29T12:00:00+01:00")))[1]
    assert any("protected event" in item for item in bad["violations"])


def test_dst_elapsed_minutes():
    s = scenario([event("overnight", "2027-03-28T00:30:00+00:00", "2027-03-28T03:30:00+01:00")])
    s._aggregate_requirements = [DurationRequirement(id="dst", kind="minimum_duration",
        event_category="work", start="2027-03-28T00:00:00+00:00",
        end="2027-03-29T00:00:00+01:00", minimum_minutes=180, complete_horizon=True)]
    report = simulate(s, proposal())[1]
    assert report["aggregate_checks"][0]["minutes"] == 120
    assert report["aggregate_checks"][0]["status"] == "fail"


def test_sidecar_import_and_tamper_detection(tmp_path):
    source_root = tmp_path / "source"
    source = source_root / "80" / "family" / "case.json"
    source.parent.mkdir(parents=True)
    s = scenario([event("a", "2027-03-29T09:00:00+01:00", "2027-03-29T11:00:00+01:00")])
    source.write_text(s.model_dump_json())
    payload = json.dumps(s.model_dump(mode="json"), sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False).encode()
    sidecar = source_root / "aggregate_requirements" / "aggregate_case.json"
    sidecar.parent.mkdir()
    sidecar.write_text(json.dumps({"schema_version": "1.0", "scenario_id": "aggregate_case",
        "scenario_sha256_canonical": hashlib.sha256(payload).hexdigest(),
        "requirements": [r.model_dump(mode="json") for r in attach(s).aggregate_requirements]}))
    target = import_scenario(tmp_path / "imported", source, "train")
    assert len(load_manifest(tmp_path / "imported")) == 1
    assert len(load_scenario(target).aggregate_requirements) == 1
    sidecar.write_text(sidecar.read_text().replace("aggregate_case", "wrong", 1))
    try:
        load_scenario(source)
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("tampered sidecar accepted")


def test_category_to_id_protection_preserves_required_events():
    s = scenario([event("client", "2027-03-29T09:00:00+01:00", "2027-03-29T10:00:00+01:00"),
                  event("flexible", "2027-03-29T11:00:00+01:00", "2027-03-29T12:00:00+01:00")])
    old = s.model_copy(deep=True)
    old.profile.hard_constraints = [V2HardConstraint(id="contract", description="Keep client appointment",
                                    rule_type="protect_events_by_category", event_categories=["work"])]
    new = old.model_copy(deep=True)
    new.profile.hard_constraints = [V2HardConstraint(id="contract", description="Keep client appointment",
                                  rule_type="protect_events_by_id", event_ids=["client"])]
    moving_flexible = proposal(Change(type="move", event_id="flexible",
                                     to_start="2027-03-29T13:00:00+01:00"))
    assert not simulate(old, moving_flexible)[1]["valid"]
    assert simulate(new, moving_flexible)[1]["valid"]
    moving_client = proposal(Change(type="move", event_id="client",
                                   to_start="2027-03-29T13:00:00+01:00"))
    assert not simulate(new, moving_client)[1]["valid"]


def test_confirmed_exception_is_exact_and_does_not_release_other_fixed_events():
    s = scenario([event("shift", "2027-03-29T09:00:00+01:00", "2027-03-29T10:00:00+01:00", fixed=True),
                  event("other", "2027-03-29T11:00:00+01:00", "2027-03-29T12:00:00+01:00", fixed=True)])
    s._confirmed_changes = [ConfirmedEventChange(event_id="shift", type="move",
                            to_start="2027-03-29T13:00:00+01:00",
                            to_end="2027-03-29T14:00:00+01:00")]
    allowed = proposal(Change(type="move", event_id="shift", to_start="2027-03-29T13:00:00+01:00"))
    assert simulate(s, allowed)[1]["valid"]
    assert not simulate(s, proposal(Change(type="move", event_id="shift",
                        to_start="2027-03-29T14:00:00+01:00")))[1]["valid"]
    assert not simulate(s, proposal(Change(type="move", event_id="other",
                        to_start="2027-03-29T13:00:00+01:00")))[1]["valid"]


def test_partner_only_availability_is_context_not_user_occupation():
    s = scenario([event("work", "2027-03-29T09:00:00+01:00", "2027-03-29T10:00:00+01:00")])
    from scenario_v2 import V2Event
    partner = V2Event(id="partner", title="Partner shift", start="2027-03-29T13:00:00+01:00",
                      end="2027-03-29T14:00:00+01:00", category="partner_work", importance=3,
                      fixed=True, participants=["partner"], description="Contextual shift")
    s.calendar.events.append(partner)
    user_only = proposal(Change(type="move", event_id="work", to_start="2027-03-29T13:00:00+01:00"))
    assert simulate(s, user_only)[1]["valid"]
    joint = proposal(Change(type="add", title="Joint appointment", event_id="joint",
                     to_start="2027-03-29T13:00:00+01:00", participants=["user", "partner"]))
    assert not simulate(s, joint)[1]["valid"]


def test_dev_family_is_isolated_from_gate_training(tmp_path):
    from gate_dataset_v2 import build_rows
    source_root = tmp_path / "sources"
    for family, split in (("train_family", "train"), ("dev_family", "dev"), ("test_family", "test")):
        s = scenario([event("a", "2027-03-29T09:00:00+01:00", "2027-03-29T11:00:00+01:00")])
        s.scenario_id, s.family_id = family, family
        s.profile.profile_id = family
        path = source_root / family / f"{family}.json"
        path.parent.mkdir(parents=True)
        path.write_text(s.model_dump_json())
        import_scenario(tmp_path / "imported", path, split)
    assert {row["split"] for row in load_manifest(tmp_path / "imported")} == {"train", "dev", "test"}
    rows, exclusions = build_rows(tmp_path / "imported", split="train")
    assert rows == exclusions == []
    assert not any(row["split"] == "dev" for row in rows)


def test_confirmed_sidecar_import_is_hash_bound(tmp_path):
    from scenario_v2 import ConfirmedChangesSidecar
    source_root = tmp_path / "source"
    source = source_root / "80" / "family" / "case.json"
    source.parent.mkdir(parents=True)
    s = scenario([event("shift", "2027-03-29T09:00:00+01:00",
                        "2027-03-29T10:00:00+01:00", fixed=True)])
    source.write_text(s.model_dump_json())
    canonical = json.dumps(s.model_dump(mode="json"), sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False).encode()
    sidecar = source_root / "confirmed_changes" / "aggregate_case.json"
    sidecar.parent.mkdir()
    sidecar.write_text(ConfirmedChangesSidecar(
        schema_version="1.0", scenario_id="aggregate_case",
        scenario_sha256_canonical=hashlib.sha256(canonical).hexdigest(),
        changes=[ConfirmedEventChange(event_id="shift", type="delete")]
    ).model_dump_json())
    target = import_scenario(tmp_path / "imported", source, "train")
    assert len(load_scenario(target).confirmed_changes) == 1
    altered = json.loads(source.read_text())
    altered["user_request"] = "Changed request"
    source.write_text(json.dumps(altered))
    try:
        load_scenario(source)
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("stale confirmed-change authorization accepted")
