"""Read-only weekly calendar tests with schema-2 inputs and synthetic request examples."""
import copy
import hashlib
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from annotation_v2_ui import (active_proposed_events, local_packet, preview,
                              proposal_change_rows, reviewer_progress)
from calendar_view import (HOUR_PX, Interval, identify_requested_interval, initial_week,
                           interval_segments, overlap_summary, render_week_html,
                           view_events, week_after, week_segments)
from models import Change, Proposal, Rationale
from scenario_v2 import load_scenario


def packet():
    scenario = load_scenario(ROOT / "data/scenarios/working_student_deadline_001.json")
    return local_packet(scenario)


def health_example():
    case = packet()
    case["scenario_id"] = "synthetic_health_visual_test"
    case["user_request"] = "Something came up on Thursday morning, clear my calendar between 9 and 12."
    case["calendar"] = [
        {"id": "lab", "title": "Agents lab", "start": "2026-11-12T09:00:00",
         "end": "2026-11-12T11:00:00", "category": "class", "importance": 5, "fixed": True},
        {"id": "dentist", "title": "Dentist appointment", "start": "2026-11-12T11:00:00",
         "end": "2026-11-12T12:00:00", "category": "health", "importance": 3, "fixed": False},
    ]
    return case


def rationale():
    return Rationale(constraints=[], priorities=[], alternatives_considered=[], summary="Synthetic preview test")


def test_target_positions_durations_and_overlap():
    case = health_example()
    interval = identify_requested_interval(case)
    assert interval == Interval(datetime(2026, 11, 12, 9), datetime(2026, 11, 12, 12),
                                "weekday + explicit morning hours")
    week = initial_week(case, interval)
    assert week == date(2026, 11, 9) and week.weekday() == 0
    events = view_events(case["calendar"])
    segments = week_segments(events, week, interval)
    lab = next(s for s in segments if s.event.id == "lab")
    dentist = next(s for s in segments if s.event.id == "dentist")
    assert (lab.top_px, lab.height_px) == (9 * HOUR_PX, 2 * HOUR_PX)
    assert (dentist.top_px, dentist.height_px) == (11 * HOUR_PX, HOUR_PX)
    assert lab.event.fixed and not dentist.event.fixed
    assert lab.in_requested_interval and dentist.in_requested_interval
    summary = overlap_summary(events, interval)
    assert (summary["total"], summary["fixed"], summary["flexible"]) == (2, 1, 1)


def test_week_navigation_and_no_invented_interval():
    case = packet()
    assert identify_requested_interval(case) is None
    start = initial_week(case, None)
    assert start == date(2026, 11, 9)
    assert week_after(start, -1) == date(2026, 11, 2)
    assert week_after(start, 1) == date(2026, 11, 16)
    html = render_week_html(view_events(case["calendar"]), start, None)
    assert "hcai-target'" not in html
    vague = health_example()
    vague["user_request"] = "Clear Thursday afternoon."
    assert identify_requested_interval(vague) is None
    vague["user_request"] = "Clear Thursday between 9 and 12."
    assert identify_requested_interval(vague) is None
    vague["user_request"] = "Clear next Thursday morning between 9 and 12."
    assert identify_requested_interval(vague) is None
    vague["user_request"] = "Do not clear Thursday morning between 9 and 12."
    assert identify_requested_interval(vague) is None


def test_explicit_cross_day_and_cross_week_requests_are_clipped():
    case = health_example()
    case["user_request"] = "Clear from 2026-11-12 23:00 to 2026-11-13 01:00."
    interval = identify_requested_interval(case)
    assert interval_segments(interval, date(2026, 11, 9)) == [
        {"day": date(2026, 11, 12), "top_px": 23 * HOUR_PX, "height_px": HOUR_PX},
        {"day": date(2026, 11, 13), "top_px": 0, "height_px": HOUR_PX}]
    case["user_request"] = "Clear from 2026-11-15 23:00 to 2026-11-16 01:00."
    cross_week = identify_requested_interval(case)
    assert interval_segments(cross_week, date(2026, 11, 9)) == [
        {"day": date(2026, 11, 15), "top_px": 23 * HOUR_PX, "height_px": HOUR_PX}]
    assert interval_segments(cross_week, date(2026, 11, 16)) == [
        {"day": date(2026, 11, 16), "top_px": 0, "height_px": HOUR_PX}]
    case["user_request"] = "Clear from 2026-11-13 01:00 to 2026-11-12 23:00."
    assert identify_requested_interval(case) is None


def test_overlapping_blocks_get_separate_lanes_and_overnight_is_clipped():
    events = view_events([
        {"id": "one", "title": "First", "start": "2026-11-12T09:00", "end": "2026-11-12T11:00",
         "category": "class", "importance": 5, "fixed": True},
        {"id": "two", "title": "Second", "start": "2026-11-12T10:00", "end": "2026-11-12T12:00",
         "category": "health", "importance": 3, "fixed": False},
        {"id": "overnight", "title": "Overnight", "start": "2026-11-15T23:00", "end": "2026-11-16T01:00",
         "category": "travel", "importance": 3, "fixed": False},
    ])
    week = week_segments(events, date(2026, 11, 9))
    a, b = (next(s for s in week if s.event.id == name) for name in ("one", "two"))
    assert {a.lane, b.lane} == {0, 1} and a.lane_count == b.lane_count == 2
    assert next(s for s in week if s.event.id == "overnight").height_px == HOUR_PX
    assert next(s for s in week_segments(events, date(2026, 11, 16))
                if s.event.id == "overnight").height_px == HOUR_PX


def test_preview_is_in_memory_and_invalid_changes_are_blocked():
    path = ROOT / "data/scenarios/working_student_deadline_001.json"
    original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    source = {"scenario_id": "working_student_deadline_001", "final_proposal": Proposal(
        changes=[Change(type="move", event_id="gym_mon", to_start="2026-11-09T20:00:00+00:00")],
        rationale=rationale()).model_dump()}
    case, original, proposed, report = preview(ROOT, source)
    assert report["valid"] and proposed is not None
    moved = next(e for e in proposed if e.id == "gym_mon" and e.change_status == "moved")
    ghost = next(e for e in proposed if e.id == "gym_mon" and e.change_status == "previous_position")
    assert moved.start.hour == 20 and ghost.start.hour == 18
    html = render_week_html(proposed, initial_week(case, None), None)
    assert "Posição anterior" in html and "Movido" in html
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original_hash
    invalid = copy.deepcopy(source)
    invalid["final_proposal"]["changes"] = [Change(type="move", event_id="work_mon",
                                                        to_start="2026-11-09T20:00:00+00:00").model_dump()]
    _, _, blocked, problems = preview(ROOT, invalid)
    assert blocked is None and problems["violations"]


def test_rendering_escapes_text_and_shows_fixed_state():
    events = view_events([{"id": "x", "title": "<script>alert(1)</script>",
                           "start": "2026-11-12T09:00", "end": "2026-11-12T10:00",
                           "category": "class", "importance": 5, "fixed": True}])
    html = render_week_html(events, date(2026, 11, 9), None)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "Fixo" in html and "09:00–10:00" in html and "duração 60 min" in html


def test_added_and_removed_events_have_explicit_status():
    source = {"scenario_id": "working_student_deadline_001", "final_proposal": Proposal(
        changes=[Change(type="delete", event_id="gym_mon"),
                 Change(type="add", event_id="new_study", title="Study block",
                        to_start="2026-11-09T18:30:00+00:00")],
        rationale=rationale()).model_dump()}
    case, _, proposed, report = preview(ROOT, source)
    assert report["valid"] and proposed is not None
    assert next(x for x in proposed if x.id == "new_study").change_status == "added"
    assert next(x for x in proposed if x.id == "gym_mon").change_status == "removed"
    html = render_week_html(proposed, initial_week(case, None), None)
    assert "Adicionado" in html and "Removido (referência)" in html
    actual = active_proposed_events(proposed)
    assert {event.id for event in actual} == ({event.id for event in proposed} - {"gym_mon"})


def test_change_overview_resolves_titles_schedules_and_every_operation():
    source = {"scenario_id": "working_student_deadline_001", "final_proposal": Proposal(
        changes=[Change(type="move", event_id="gym_mon",
                        to_start="2026-11-09T20:00:00+00:00",
                        to_end="2026-11-09T21:30:00+00:00"),
                 Change(type="delete", event_id="work_tue"),
                 Change(type="add", title="Short check-in",
                        to_start="2026-11-10T18:05:00+00:00",
                        to_end="2026-11-10T18:15:00+00:00")],
        rationale=rationale()).model_dump(mode="json")}
    rows = proposal_change_rows(ROOT, source)
    assert [row["sequence"] for row in rows] == [1, 2, 3]
    assert [row["operation"] for row in rows] == ["MOVE", "DELETE", "ADD"]
    assert rows[0]["event"] == "Gym"
    assert "18:30" in rows[0]["original_schedule"] and "20:00" in rows[0]["proposed_schedule"]
    assert rows[1]["event"] == "Work" and rows[1]["proposed_schedule"] == "—"
    assert rows[2]["event"] == "Short check-in" and "10 min" in rows[2]["proposed_schedule"]


def test_short_events_keep_actual_timeline_height_and_accessible_details():
    events = view_events([{"id": "short", "title": "Ten minute event with a full title",
                           "start": "2026-11-12T09:00", "end": "2026-11-12T09:10",
                           "category": "meeting", "importance": 3, "fixed": False}])
    segment = week_segments(events, date(2026, 11, 9))[0]
    assert segment.height_px == 10
    html = render_week_html(events, date(2026, 11, 9), None, comparison_palette=True)
    assert "Ten minute event with a full title" in html
    assert "duração 10 min" in html and "hcai-comparison" in html


def test_reviewer_progress_is_independent_and_family_scoped():
    rows = [
        {"family_id": "family_a", "state": "complete"},
        {"family_id": "family_a", "state": "draft"},
        {"family_id": "family_b", "state": "complete"},
    ]
    assert reviewer_progress(rows, "family_a") == {
        "family_total": 2, "family_complete": 1, "family_remaining": 1,
        "overall_total": 3, "overall_complete": 2, "overall_remaining": 1}
