"""Safe presentation adapter for v2 proposals; no persisted scientific data edits."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from annotation_v2 import AUTHORS, _consensus_path, load_review
from calendar_v2 import simulate
from calendar_view import view_events
from models import Proposal
from proposal_catalog_v2 import catalog, training_catalog
from scenario_v2 import load_scenario
from final_dataset_v2 import scenario_path

FAMILY_DISPLAY_NAMES = {
    "elite_athlete_student_schedule_conflict": "Atleta-estudante",
    "content_creator_schedule_conflict": "Criador de conteúdos",
    "nurse_shift_worker_masters_schedule_conflict": "Enfermeira-estudante",
    "freelancer_schedule_conflict": "Freelancer",
    "parent_young_children_schedule_conflict": "Pai/mãe com filhos pequenos",
    "working_student_schedule_conflict": "Trabalhador-estudante",
}


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
    scenario = load_scenario(scenario_path(root, source["scenario_id"]))
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


def active_proposed_events(events: list | None) -> list:
    """Actual proposed calendar only; visual deletion ghosts are excluded."""
    return [event for event in (events or [])
            if event.change_status not in ("removed", "previous_position")]


def _display_schedule(start: datetime | None, end: datetime | None) -> str:
    if start is None:
        return "—"
    if end is None:
        return start.strftime("%d %b, %H:%M")
    minutes = int((end - start).total_seconds() // 60)
    if start.date() == end.date():
        return f"{start:%d %b}, {start:%H:%M}–{end:%H:%M} ({minutes} min)"
    return f"{start:%d %b %H:%M}–{end:%d %b %H:%M} ({minutes} min)"


def proposal_change_rows(root: Path, source: dict) -> list[dict]:
    """Human-readable, complete operation overview without changing sequence semantics."""
    scenario = load_scenario(scenario_path(root, source["scenario_id"]))
    proposal = Proposal.model_validate(source["final_proposal"])
    after, _ = simulate(scenario, proposal)
    original = {event.id: event for event in scenario.calendar.events}
    final = {event.id: event for event in (after or [])}
    rows = []
    for index, change in enumerate(proposal.changes):
        event_id = change.event_id or f"new_{index}"
        before = original.get(event_id)
        proposed = final.get(event_id)
        proposed_start = proposed.start if proposed is not None else None
        proposed_end = proposed.end if proposed is not None else None
        # Invalid scientific outcomes have no simulated final calendar, but the
        # annotator must still see every concrete operation exactly as proposed.
        if proposed is None and change.type in ("add", "move") and change.to_start:
            proposed_start = datetime.fromisoformat(change.to_start)
            if change.to_end:
                proposed_end = datetime.fromisoformat(change.to_end)
            elif before is not None:
                proposed_end = proposed_start + (before.end - before.start)
            else:
                proposed_end = proposed_start + timedelta(hours=1)
        title = change.title or (before.title if before is not None else event_id)
        rows.append({
            "sequence": index + 1,
            "operation": change.type.upper(),
            "event": title,
            "event_id": event_id,
            "original_schedule": _display_schedule(
                before.start if before else None, before.end if before else None),
            "proposed_schedule": _display_schedule(
                proposed_start, proposed_end),
            "description": (before.description if before is not None else
                            proposed.description if proposed is not None else ""),
        })
    return rows


def reviewer_progress(rows: list[dict], family_id: str) -> dict:
    family = [row for row in rows if row["family_id"] == family_id]
    family_complete = sum(row["state"] == "complete" for row in family)
    overall_complete = sum(row["state"] == "complete" for row in rows)
    return {
        "family_total": len(family), "family_complete": family_complete,
        "family_remaining": len(family) - family_complete,
        "overall_total": len(rows), "overall_complete": overall_complete,
        "overall_remaining": len(rows) - overall_complete,
    }


def records(root: Path, author: str, *, training_only: bool = False,
            sources: list[dict] | None = None) -> list[dict]:
    if author not in AUTHORS:
        raise ValueError("unknown author")
    if sources is None:
        sources = training_catalog(root) if training_only else catalog(root)
    rows = []
    for source in sources:
        review_path = (root / "data" / "annotations" / author
                       / f"{source['proposal_id']}.json")
        if not review_path.exists():
            rows.append({"id": source["proposal_id"], "scenario_id": source["scenario_id"],
                         "profile_id": source["profile_id"], "family_id": source["family_id"],
                         "state": "not_started"})
            continue
        try:
            form, _ = load_review(root, author, source["proposal_id"], source=source)
            state = "complete" if form.status == "complete" else (
                "draft" if any([form.scheduling_acceptable, form.autonomy_decision,
                                form.primary_reason, form.justification]) else "not_started")
        except (ValueError, OSError):
            state = "needs_correction"
        rows.append({"id": source["proposal_id"], "scenario_id": source["scenario_id"],
                     "profile_id": source["profile_id"], "family_id": source["family_id"],
                     "state": state})
    return rows
