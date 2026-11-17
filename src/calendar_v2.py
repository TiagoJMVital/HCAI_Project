"""Pure simulation and limited deterministic checks for timezone-aware v2 scenarios."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from models import Proposal
from scenario_v2 import V2Event, V2Scenario


def _parse(value: str, zone: ZoneInfo) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("proposal timestamps require an explicit timezone offset")
    if moment.utcoffset() != moment.astimezone(zone).utcoffset():
        raise ValueError("proposal timestamp offset disagrees with profile timezone")
    return moment


def simulate(scenario: V2Scenario, proposal: Proposal) -> tuple[list[V2Event] | None, dict]:
    """Return a new calendar only if all implemented hard checks pass.

    Natural-language request satisfaction, soft preferences and the prose of
    constraints are explicitly outside this validator's claims.
    """
    original = {e.id: e for e in scenario.calendar.events}
    events = dict(original)
    problems: list[str] = []
    warnings: list[str] = []
    touched: set[str] = set()
    zone = ZoneInfo(scenario.profile.timezone)
    protected_categories = {cat for rule in scenario.profile.hard_constraints
                            if rule.rule_type == "protect_events_by_category"
                            for cat in rule.event_categories or []}
    protected_ids = {eid for rule in scenario.profile.hard_constraints
                     if rule.rule_type == "protect_events_by_id" for eid in rule.event_ids or []}
    if not proposal.changes:
        problems.append("proposal has no concrete changes")
    for index, change in enumerate(proposal.changes):
        eid = change.event_id or f"new_{index}"
        try:
            if eid in touched:
                raise ValueError(f"event changed more than once: {eid}")
            if change.type == "add":
                if eid in events:
                    raise ValueError(f"duplicate added event id: {eid}")
                start = _parse(change.to_start, zone)
                end = _parse(change.to_end, zone) if change.to_end else start + timedelta(hours=1)
                if end <= start:
                    raise ValueError(f"nonpositive duration: {eid}")
                events[eid] = V2Event(id=eid, title=change.title, start=start, end=end,
                                      category="other", importance=3, fixed=False,
                                      participants=["user"], description="Added by proposal; metadata unspecified")
                warnings.append(f"{eid}: added-event category, importance and participants were not supplied by the Proposal contract; preview uses neutral defaults")
            else:
                if eid not in events or eid not in original:
                    raise ValueError(f"unknown or repeated event reference: {eid}")
                prior = events[eid]
                if prior.fixed or eid in protected_ids or prior.category in protected_categories:
                    raise ValueError(f"protected event cannot be changed: {eid}")
                if change.type == "delete":
                    del events[eid]
                else:
                    start = _parse(change.to_start, zone)
                    end = _parse(change.to_end, zone) if change.to_end else start + (prior.end - prior.start)
                    if end <= start:
                        raise ValueError(f"nonpositive duration: {eid}")
                    events[eid] = prior.model_copy(update={"start": start, "end": end})
            touched.add(eid)
        except (ValueError, TypeError) as exc:
            problems.append(f"change {index + 1}: {exc}")
    if not problems:
        new_soft_overlaps: set[tuple[str, str]] = set()
        for eid in touched & events.keys():
            event = events[eid]
            local_start, local_end = event.start.astimezone(zone), event.end.astimezone(zone)
            if (event.start.utcoffset() != local_start.utcoffset() or
                    event.end.utcoffset() != local_end.utcoffset()):
                problems.append(f"{eid}: computed timestamp offset disagrees with profile timezone")
            for rule in scenario.profile.hard_constraints:
                if rule.rule_type == "daily_time_window":
                    if (local_start.date() != local_end.date() or
                            local_start.time().replace(tzinfo=None) < rule.start or
                            local_end.time().replace(tzinfo=None) > rule.end):
                        problems.append(f"{eid}: outside typed daily_time_window {rule.id}")
            for other in events.values():
                if other.id == eid:
                    continue
                if event.start < other.end and other.start < event.end:
                    if other.fixed or other.id in protected_ids or other.category in protected_categories:
                        problems.append(f"{eid}: overlaps protected event {other.id}")
                    else:
                        pair = tuple(sorted((eid, other.id)))
                        old_a, old_b = original.get(pair[0]), original.get(pair[1])
                        existed = bool(old_a and old_b and old_a.start < old_b.end and old_b.start < old_a.end)
                        if not existed:
                            new_soft_overlaps.add(pair)
        warnings.extend(f"new temporal overlap (not automatically a hard-rule violation): {a} x {b}"
                        for a, b in sorted(new_soft_overlaps))
        if all(events.get(eid) == event for eid, event in original.items()) and len(events) == len(original):
            problems.append("proposal produces no effective change")
    report = {"structural": "valid", "scope": "implemented_typed_checks_only",
              "checked_rules": ["event references", "fixed event protection",
              "typed category/id protection", "typed daily time window", "timezone offsets",
              "positive duration", "overlap with protected events"],
              "not_checked": ["natural-language constraint descriptions", "request satisfaction",
                              "soft preference satisfaction", "autonomy suitability"],
              "violations": problems, "warnings": warnings, "valid": not problems}
    return (sorted(events.values(), key=lambda e: e.start) if not problems else None), report
