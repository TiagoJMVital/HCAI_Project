"""Safe presentation adapter for v2 proposals; no persisted scientific data edits."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from annotation_v2 import AUTHORS, _consensus_path, load_review, prepare
from calendar_v2 import simulate
from calendar_view import view_events
from models import Proposal
from proposal_catalog_v2 import catalog
from scenario_v2 import load_scenario


def temporal_overlaps(events: list) -> list[tuple[str, str]]:
    """Factual overlap pairs among active events, not hard-rule violations."""
    active = [event for event in events if event.change_status not in ("removed", "previous_position")]
    return [(a.title, b.title) for i, a in enumerate(active) for b in active[i + 1:]
            if a.start < b.end and b.start < a.end]


def local_packet(scenario) -> dict:
    """Convert timestamps only for the existing naive read-only calendar widget."""
    zone = ZoneInfo(scenario.profile.timezone)
    events = []
    for event in scenario.calendar.events:
        raw = event.model_dump(mode="json")
        for key in ("start", "end"):
            raw[key] = getattr(event, key).astimezone(zone).replace(tzinfo=None).isoformat()
        events.append(raw)
    return {"scenario_id": scenario.scenario_id, "user_request": scenario.user_request,
            "now": scenario.now.astimezone(zone).replace(tzinfo=None).isoformat(),
            "calendar": events}


def preview(root: Path, source: dict) -> tuple[dict, list, list | None, dict]:
    scenario = load_scenario(root / "data" / "scenarios" / f"{source['scenario_id']}.json")
    proposal = Proposal.model_validate(source["final_proposal"])
    after, validation = simulate(scenario, proposal)
    packet = local_packet(scenario)
    original = view_events(packet["calendar"])
    proposed = None
    if after is not None:
        zone = ZoneInfo(scenario.profile.timezone)
        before = {e.id: e for e in scenario.calendar.events}
        current = {e.id: e for e in after}
        status = {e.id: ("added" if e.id not in before else
                         "moved" if (e.start, e.end) != (before[e.id].start, before[e.id].end)
                         else "preserved") for e in after}
        local_after = []
        for event in after:
            raw = event.model_dump(mode="json")
            for key in ("start", "end"):
                raw[key] = getattr(event, key).astimezone(zone).replace(tzinfo=None).isoformat()
            local_after.append(raw)
        proposed = view_events(local_after, status_by_id=status)
        for event in scenario.calendar.events:
            if event.id not in current or status.get(event.id) == "moved":
                raw = next(e for e in packet["calendar"] if e["id"] == event.id)
                ghost = "removed" if event.id not in current else "previous_position"
                proposed.extend(view_events([raw], status_by_id={event.id: ghost}))
    return packet, original, proposed, validation


def records(root: Path, author: str) -> list[dict]:
    if author not in AUTHORS:
        raise ValueError("unknown author")
    prepare(root, author)
    rows = []
    for source in catalog(root):
        try:
            form, _ = load_review(root, author, source["proposal_id"])
            state = "complete" if form.status == "complete" else (
                "draft" if any([form.scheduling_acceptable, form.autonomy_decision,
                                form.primary_reason, form.justification]) else "not_started")
        except (ValueError, OSError):
            state = "needs_correction"
        rows.append({"id": source["proposal_id"], "scenario_id": source["scenario_id"],
                     "profile_id": source["profile_id"], "family_id": source["family_id"],
                     "state": state})
    return rows
