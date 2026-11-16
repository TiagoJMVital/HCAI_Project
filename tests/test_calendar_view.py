"""Weekly visualization tests use synthetic inputs and never edit annotations."""
import copy
import hashlib
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from calendar_view import (  # noqa: E402
    HOUR_PX, Interval, identify_requested_interval, initial_week,
    interval_segments, overlap_summary, proposed_events, render_week_html,
    view_events, week_after, week_segments,
)


def packet(scenario_id):
    scenario = json.loads((ROOT / "data" / "scenarios" / f"{scenario_id}.json").read_text())
    return {"scenario_id": scenario["id"], "user_request": scenario["user_request"],
            "now": scenario["now"], "calendar": scenario["calendar"],
            "profile": json.loads((ROOT / "data" / "profile.json").read_text())}


def test_amb_health_target_event_positions_durations_and_overlap():
    scenario = packet("amb_health_01")
    interval = identify_requested_interval(scenario)
    assert interval == Interval(datetime(2026, 11, 12, 9), datetime(2026, 11, 12, 12),
                                "weekday + explicit morning hours")
    week = initial_week(scenario, interval)
    assert week == date(2026, 11, 9) and week.weekday() == 0
    events = view_events(scenario["calendar"])
    segments = week_segments(events, week, interval)
    lab = next(s for s in segments if s.event.title == "Agents lab")
    dentist = next(s for s in segments if s.event.title == "Dentist appointment")
    assert (lab.day, lab.top_px, lab.height_px) == (date(2026, 11, 12), 9 * HOUR_PX, 2 * HOUR_PX)
    assert (dentist.day, dentist.top_px, dentist.height_px) == (date(2026, 11, 12), 11 * HOUR_PX, HOUR_PX)
    assert lab.event.fixed and not dentist.event.fixed
    assert lab.in_requested_interval and dentist.in_requested_interval
    assert interval_segments(interval, week) == [
        {"day": date(2026, 11, 12), "top_px": 9 * HOUR_PX, "height_px": 3 * HOUR_PX}]
    summary = overlap_summary(events, interval)
    assert (summary["total"], summary["fixed"], summary["flexible"]) == (2, 1, 1)


def test_week_navigation_and_no_invented_interval():
    scenario = packet("health_specificity_01")
    assert identify_requested_interval(scenario) is None  # 'Thursday afternoon' is vague.
    start = initial_week(scenario, None)
    assert start == date(2026, 11, 9)
    assert week_after(start, -1) == date(2026, 11, 2)
    assert week_after(start, 1) == date(2026, 11, 16)
    html = render_week_html(view_events(scenario["calendar"]), start, None)
    assert "hcai-target'" not in html
    ambiguous = copy.deepcopy(scenario)
    ambiguous["user_request"] = "Clear Thursday between 9 and 12."
    assert identify_requested_interval(ambiguous) is None  # 12-hour clock lacks qualifier.
    ambiguous["user_request"] = "Clear Thursday morning between 9 and 12, then Friday too."
    assert identify_requested_interval(ambiguous) is None  # Multiple named days.
    ambiguous["user_request"] = "Clear next Thursday morning between 9 and 12."
    assert identify_requested_interval(ambiguous) is None  # 'next' is not inferred.
    ambiguous["user_request"] = "Do not clear Thursday morning between 9 and 12."
    assert identify_requested_interval(ambiguous) is None  # Negated action.


def test_explicit_cross_day_and_cross_week_requests_are_clipped():
    scenario = packet("amb_health_01")
    scenario["user_request"] = "Clear from 2026-11-12 23:00 to 2026-11-13 01:00."
    interval = identify_requested_interval(scenario)
    assert interval.start == datetime(2026, 11, 12, 23)
    assert interval.end == datetime(2026, 11, 13, 1)
    slices = interval_segments(interval, date(2026, 11, 9))
    assert [(s["day"], s["top_px"], s["height_px"]) for s in slices] == [
        (date(2026, 11, 12), 23 * HOUR_PX, HOUR_PX),
        (date(2026, 11, 13), 0, HOUR_PX)]
    scenario["user_request"] = "Clear from 2026-11-15 23:00 to 2026-11-16 01:00."
    cross_week = identify_requested_interval(scenario)
    assert interval_segments(cross_week, date(2026, 11, 9)) == [
        {"day": date(2026, 11, 15), "top_px": 23 * HOUR_PX, "height_px": HOUR_PX}]
    assert interval_segments(cross_week, date(2026, 11, 16)) == [
        {"day": date(2026, 11, 16), "top_px": 0, "height_px": HOUR_PX}]
    scenario["user_request"] = "Clear from 2026-11-13 01:00 to 2026-11-12 23:00."
    assert identify_requested_interval(scenario) is None


def test_event_crosses_days_and_overlapping_blocks_get_separate_lanes():
    day = date(2026, 11, 12)
    events = view_events([
        {"id": "one", "title": "First", "start": "2026-11-12T09:00",
         "end": "2026-11-12T11:00", "category": "class", "importance": 5, "fixed": True},
        {"id": "two", "title": "Second", "start": "2026-11-12T10:00",
         "end": "2026-11-12T12:00", "category": "health", "importance": 3, "fixed": False},
        {"id": "overnight", "title": "Overnight", "start": "2026-11-15T23:00",
         "end": "2026-11-16T01:00", "category": "travel", "importance": 3, "fixed": False},
    ])
    first_week = week_segments(events, date(2026, 11, 9))
    a, b = (next(s for s in first_week if s.event.id == name) for name in ("one", "two"))
    assert a.day == b.day == day
    assert {a.lane, b.lane} == {0, 1} and a.lane_count == b.lane_count == 2
    assert next(s for s in first_week if s.event.id == "overnight").height_px == HOUR_PX
    assert next(s for s in week_segments(events, date(2026, 11, 16))
                if s.event.id == "overnight").height_px == HOUR_PX


def test_proposed_preview_is_in_memory_blinded_and_rejects_invalid_changes():
    scenario_path = ROOT / "data" / "scenarios" / "amb_health_01.json"
    original_hash = hashlib.sha256(scenario_path.read_bytes()).hexdigest()
    scenario = packet("amb_health_01")
    original = copy.deepcopy(scenario)
    rationale = {"constraints": [], "priorities": [], "alternatives_considered": [],
                 "summary": "Synthetic preview test"}
    packet_data = {"scenario": scenario,
                   "final_proposal": {"changes": [{"type": "move", "event_id": "dentist",
                                                   "to_start": "2026-11-12T13:00"}],
                                      "rationale": rationale},
                   "critic_score": 5, "draft_label": "act", "split": "test"}
    proposed, problems = proposed_events(packet_data)
    assert problems == [] and proposed is not None
    moved = next(event for event in proposed if event.id == "dentist" and event.change_status == "moved")
    ghost = next(event for event in proposed if event.id == "dentist" and event.change_status == "previous_position")
    assert moved.start.hour == 13 and ghost.start.hour == 11
    interval = identify_requested_interval(scenario)
    summary = overlap_summary(proposed, interval)
    assert (summary["total"], summary["fixed"], summary["flexible"]) == (1, 1, 0)
    html = render_week_html(proposed, initial_week(scenario, interval), interval)
    assert "Posição anterior" in html and "Movido" in html
    assert "critic_score" not in html and "draft_label" not in html and "split" not in html
    assert scenario == original and hashlib.sha256(scenario_path.read_bytes()).hexdigest() == original_hash

    invalid = copy.deepcopy(packet_data)
    invalid["final_proposal"]["changes"] = [{"type": "move", "event_id": "cls_agents",
                                               "to_start": "2026-11-12T13:00"}]
    blocked, violations = proposed_events(invalid)
    assert blocked is None and any("fixo" in item for item in violations)
    malformed = copy.deepcopy(packet_data)
    malformed["final_proposal"]["changes"] = [{"type": "add", "title": "Missing time"}]
    blocked, violations = proposed_events(malformed)
    assert blocked is None and violations


def test_rendering_escapes_event_text_and_shows_fixed_state():
    events = view_events([{"id": "x", "title": "<script>alert(1)</script>",
                           "start": "2026-11-12T09:00", "end": "2026-11-12T10:00",
                           "category": "class", "importance": 5, "fixed": True}])
    html = render_week_html(events, date(2026, 11, 9), None)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Fixo" in html and "09:00–10:00" in html
    assert "hcai-academic" in html


def test_added_and_removed_events_have_explicit_preview_status():
    scenario = packet("amb_health_01")
    proposal_packet = {"scenario": scenario, "final_proposal": {
        "changes": [{"type": "delete", "event_id": "dentist"},
                    {"type": "add", "event_id": "new_study", "title": "Study block",
                     "to_start": "2026-11-13T14:00"}],
        "rationale": {"constraints": [], "priorities": [],
                      "alternatives_considered": [], "summary": "Synthetic preview test"}}}
    preview, problems = proposed_events(proposal_packet)
    assert problems == [] and preview is not None
    assert next(x for x in preview if x.id == "new_study").change_status == "added"
    assert next(x for x in preview if x.id == "dentist").change_status == "removed"
    assert overlap_summary(preview, identify_requested_interval(scenario))["total"] == 1
    html = render_week_html(preview, date(2026, 11, 9), identify_requested_interval(scenario))
    assert "Adicionado" in html and "Removido (referência)" in html
