"""Testes sem Ollama: lógica de calendário, regras e prompt."""
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from calendar_ops import apply_changes, find_violations  # noqa: E402
from models import Alternative, Change, Profile, Proposal, Rationale, Scenario  # noqa: E402
from proposer import build_prompt  # noqa: E402
from rules import rule_based_decision  # noqa: E402

profile = Profile.model_validate_json((ROOT / "data" / "profile.json").read_text(encoding="utf-8"))


def scen(id):
    return Scenario.model_validate(json.loads((ROOT / "data" / "scenarios" / f"{id}.json").read_text(encoding="utf-8")))


def prop(*changes):
    return Proposal(changes=list(changes), rationale=Rationale(
        constraints=["c"], priorities=["p"],
        alternatives_considered=[Alternative(option="o", rejected_because="r")], summary="s"))


def test_gym_move_is_valid_and_acts():
    s = scen("soft_gym_01")
    p = prop(Change(type="move", event_id="gym_wed", to_start="2026-11-11T20:00"))
    assert find_violations(s.calendar, p, profile) == []
    assert rule_based_decision(p, s.calendar, [])[0] == "act"


def test_overlap_with_class_is_violation():
    s = scen("hard_class_01")
    p = prop(Change(type="add", title="Call", to_start="2026-11-11T10:30", to_end="2026-11-11T11:30"))
    assert any("sobrepõe" in v for v in find_violations(s.calendar, p, profile))


def test_moving_fixed_event_is_violation():
    s = scen("hard_class_01")
    p = prop(Change(type="move", event_id="cls_hcai", to_start="2026-11-11T14:00"))
    assert any("fixo" in v for v in find_violations(s.calendar, p, profile))


def test_unknown_event_and_bad_date():
    s = scen("soft_gym_01")
    assert find_violations(s.calendar, prop(Change(type="delete", event_id="nope")), profile)
    assert find_violations(s.calendar, prop(Change(type="move", event_id="gym_wed", to_start="amanhã")), profile)


def test_delete_and_sensitive_defer():
    s = scen("amb_super_01")
    p = prop(Change(type="move", event_id="super_fri", to_start="2026-11-13T17:00"))
    d, reasons = rule_based_decision(p, s.calendar, [])
    assert d == "defer" and reasons


def test_weekend_and_hours_violations():
    s = scen("soft_gym_01")
    assert find_violations(s.calendar, prop(Change(type="move", event_id="gym_wed", to_start="2026-11-14T10:00")), profile)
    assert find_violations(s.calendar, prop(Change(type="move", event_id="gym_wed", to_start="2026-11-11T23:30")), profile)


def test_apply_keeps_duration():
    s = scen("soft_gym_01")
    after = apply_changes(s.calendar, [Change(type="move", event_id="gym_wed", to_start="2026-11-11T20:00")])
    g = next(e for e in after if e.id == "gym_wed")
    assert g.end == "2026-11-11T21:00"


def test_prompt_mentions_request_and_fixed():
    s = scen("soft_gym_01")
    t = build_prompt(profile, s)
    assert s.user_request in t and "[FIXED]" in t


@pytest.mark.parametrize("fields", [
    {"type": "add", "title": "Study"},
    {"type": "add", "to_start": "2026-11-11T18:00"},
    {"type": "move", "event_id": "gym_wed"},
    {"type": "move", "to_start": "2026-11-11T18:00"},
    {"type": "delete"},
])
def test_change_requires_operational_fields(fields):
    with pytest.raises(ValidationError):
        Change.model_validate(fields)


def test_old_false_success_cannot_be_parsed():
    old = json.loads((ROOT / "eval" / "results" / "A" / "soft_gym_01.json").read_text())
    with pytest.raises(ValidationError):
        Proposal.model_validate(old["proposal"])


def test_no_op_and_duplicate_add_cannot_act():
    s = scen("soft_gym_01")
    no_op = prop(Change(type="move", event_id="gym_wed", to_start="2026-11-11T18:00"))
    problems = find_violations(s.calendar, no_op, profile)
    assert any("sem alteração" in item for item in problems)
    assert rule_based_decision(no_op, s.calendar, problems)[0] == "defer"

    duplicate = prop(Change(type="add", event_id="gym_wed", title="Extra",
                            to_start="2026-11-11T20:00"))
    problems = find_violations(s.calendar, duplicate, profile)
    assert any("já existe" in item for item in problems)
    assert rule_based_decision(duplicate, s.calendar, problems)[0] == "defer"
