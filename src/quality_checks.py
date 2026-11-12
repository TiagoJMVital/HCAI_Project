"""Avaliação objetiva parcial, separada do Critic e dos rótulos de autonomia."""
from __future__ import annotations

from datetime import datetime

from pydantic import ValidationError

from calendar_ops import apply_changes, find_violations
from models import Profile, Proposal, Scenario


def _added_event_check(check: dict, original_ids: set[str], after: list) -> bool:
    for event in after:
        if event.id in original_ids:
            continue
        title = event.title.lower()
        if not any(word.lower() in title for word in check["title_any"]):
            continue
        start, end = datetime.fromisoformat(event.start), datetime.fromisoformat(event.end)
        if check.get("day") and start.date().isoformat() != check["day"]:
            continue
        if check.get("earliest") and start.strftime("%H:%M") < check["earliest"]:
            continue
        if check.get("latest_end") and end.strftime("%H:%M") > check["latest_end"]:
            continue
        if check.get("earliest_datetime") and event.start < check["earliest_datetime"]:
            continue
        if check.get("latest_datetime") and event.end > check["latest_datetime"]:
            continue
        if (end - start).total_seconds() / 60 < check["duration_min"]:
            continue
        return True
    return False


def evaluate_proposal(scenario: Scenario, profile: Profile, proposal_data: dict,
                      request_checks: list[dict] | None = None) -> dict:
    result = {
        "structural": {"status": "not_evaluated"},
        "applicability": {"status": "not_evaluated"},
        "constraints": {"status": "not_evaluated", "coverage": "partial"},
        "request_satisfaction": {"status": "unknown", "checks": []},
        "rationale_quality": {"status": "not_assessed"},
        "autonomy_appropriateness": {"status": "not_assessed"},
    }
    try:
        proposal = Proposal.model_validate(proposal_data)
    except (ValidationError, TypeError, ValueError):
        result["structural"] = {"status": "fail"}
        return result
    result["structural"] = {"status": "pass"}
    try:
        violations = find_violations(scenario.calendar, proposal, profile)
    except Exception:
        result["applicability"] = {"status": "error"}
        result["constraints"] = {"status": "error", "coverage": "partial"}
        return result
    result["constraints"] = {"status": "fail" if violations else "pass",
                             "coverage": "partial", "violations": violations}
    result["applicability"] = {"status": "fail" if violations or not proposal.changes else "pass"}
    if violations or not proposal.changes:
        return result
    if not request_checks:
        return result
    after = apply_changes(scenario.calendar, proposal.changes)
    original_ids = {event.id for event in scenario.calendar}
    checks = []
    for check in request_checks:
        if check["type"] == "added_event":
            passed = _added_event_check(check, original_ids, after)
        elif check["type"] == "moved_event":
            before = next((event for event in scenario.calendar
                           if event.id == check["event_id"]), None)
            current = next((event for event in after
                            if event.id == check["event_id"]), None)
            passed = bool(before and current and current.start == check["to_start"]
                          and before.start != current.start)
        else:
            raise ValueError(f"tipo de check desconhecido: {check['type']}")
        checks.append({"type": check["type"], "passed": passed})
    result["request_satisfaction"] = {
        "status": "partial_conditions_pass" if all(c["passed"] for c in checks) else "fail",
        "checks": checks,
        "scope": "Condições codificadas; não demonstra satisfação integral do pedido",
    }
    return result
