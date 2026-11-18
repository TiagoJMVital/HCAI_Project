"""Shared proposal contract, deterministic safety and fixed-rule baseline."""
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from calendar_v2 import simulate
from models import Alternative, Change, Proposal, Rationale
from rules import rule_based_decision
from scenario_v2 import load_scenario


@pytest.fixture
def scenario():
    return load_scenario(ROOT / "data/scenarios/working_student_deadline_001.json")


def proposal(*changes):
    return Proposal(changes=list(changes), rationale=Rationale(
        constraints=["work is protected"], priorities=["study"],
        alternatives_considered=[Alternative(option="another day", rejected_because="deadline")],
        summary="Synthetic regression case"))


@pytest.mark.parametrize("fields", [
    {"type": "add", "title": "Study"},
    {"type": "add", "to_start": "2026-11-09T18:00:00+00:00"},
    {"type": "move", "event_id": "gym_mon"},
    {"type": "move", "to_start": "2026-11-09T18:00:00+00:00"},
    {"type": "delete"},
])
def test_required_fields_by_change_type(fields):
    with pytest.raises(ValidationError):
        Change.model_validate(fields)


def test_valid_flexible_move_and_fixed_rules(scenario):
    p = proposal(Change(type="move", event_id="gym_mon", to_start="2026-11-09T20:00:00+00:00"))
    after, report = simulate(scenario, p)
    assert after is not None and report["valid"]
    assert rule_based_decision(p, scenario.calendar.events, report["violations"])[0] == "act"
    assert next(e for e in after if e.id == "gym_mon").end.isoformat().startswith("2026-11-09T21:30")
    assert scenario.calendar.events[2].start.isoformat().startswith("2026-11-09T18:30")


def test_fixed_event_and_unknown_reference_cannot_act(scenario):
    for p in (proposal(Change(type="move", event_id="work_mon", to_start="2026-11-09T20:00:00+00:00")),
              proposal(Change(type="delete", event_id="unknown"))):
        after, report = simulate(scenario, p)
        assert after is None and report["violations"]
        assert rule_based_decision(p, scenario.calendar.events, report["violations"])[0] == "defer"


def test_noop_duplicate_add_and_out_of_window_are_rejected(scenario):
    candidates = [
        proposal(Change(type="move", event_id="gym_mon", to_start="2026-11-09T18:30:00+00:00")),
        proposal(Change(type="add", event_id="gym_mon", title="Duplicate", to_start="2026-11-09T20:00:00+00:00")),
        proposal(Change(type="move", event_id="gym_mon", to_start="2026-11-09T23:30:00+00:00")),
    ]
    for p in candidates:
        assert simulate(scenario, p)[0] is None


def test_overlap_with_protected_event_is_rejected(scenario):
    p = proposal(Change(type="add", title="Conflicting call", to_start="2026-11-09T10:00:00+00:00"))
    assert any("overlaps protected" in reason for reason in simulate(scenario, p)[1]["violations"])


def test_delete_and_many_changes_still_defer(scenario):
    deletion = proposal(Change(type="delete", event_id="gym_mon"))
    assert simulate(scenario, deletion)[1]["valid"]
    assert rule_based_decision(deletion, scenario.calendar.events, [])[0] == "defer"
    many = proposal(Change(type="move", event_id="gym_mon", to_start="2026-11-09T20:00:00+00:00"),
                    Change(type="add", title="Study", to_start="2026-11-09T18:30:00+00:00"),
                    Change(type="add", title="Study again", to_start="2026-11-10T20:00:00+00:00"))
    assert simulate(scenario, many)[1]["valid"]
    assert rule_based_decision(many, scenario.calendar.events, [])[0] == "defer"
