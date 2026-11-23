"""Read-only discovery and deterministic previews for schema-2 A/B runs."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

from calendar_v2 import simulate
from models import Proposal
from scenario_v2 import load_manifest, load_scenario

PILOT_SCENARIO_IDS = (
    "working_student_makeup_class_friday_family_dinner_008",
    "working_student_month_end_overtime_friday_005",
    "freelancer_flexible_medical_appointment_birthday_dinner_001",
    "freelancer_flexible_client_meeting_gaming_tournament_001",
    "nurse_shift_worker_masters_clinical_data_collection_001",
    "nurse_shift_worker_masters_shift_changes_001",
    "elite_athlete_student_exam_conflict_001",
    "elite_athlete_student_transport_strike_001",
    "content_creator_agency_photoshoot_001",
    "parent_young_children_car_breakdown_solo_001",
)


def runs(root: Path, *, scenario_id: str | None = None,
         configuration: str | None = None) -> list[dict]:
    """Return immutable run records with their source paths, newest first."""
    if configuration not in {None, "A", "B"}:
        raise ValueError("configuration must be A or B")
    manifest = {row["scenario_id"]: row for row in load_manifest(root)}
    found = []
    for path in sorted((root / "eval" / "runs").glob("*/*/*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        config = record.get("configuration")
        sid = record.get("scenario_id")
        if record.get("schema_version") != "2.0" or config not in {"A", "B"}:
            continue
        if sid not in manifest or (scenario_id is not None and sid != scenario_id):
            continue
        if configuration is not None and config != configuration:
            continue
        row = manifest[sid]
        if (record.get("family") != row["family_id"] or
                record.get("profile_id") != row["profile_id"] or
                record.get("split") != row["split"]):
            raise ValueError(f"run provenance mismatch: {path}")
        if record.get("run_id") != path.parts[-3]:
            raise ValueError(f"run ID/path mismatch: {path}")
        item = dict(record)
        item["_path"] = str(path.relative_to(root))
        scenario_path = root / "data" / "scenarios" / f"{sid}.json"
        item["_active_scenario_sha256"] = hashlib.sha256(scenario_path.read_bytes()).hexdigest()
        item["_scenario_hash_matches"] = (record.get("scenario_sha256") == item["_active_scenario_sha256"]
                                           if record.get("scenario_sha256") else None)
        found.append(item)
    return sorted(found, key=lambda row: (row.get("generated_at") or "", row["run_id"]),
                  reverse=True)


def proposal(record: dict, *, initial: bool = False) -> Proposal | None:
    raw = (record.get("initial_proposal") if initial and record.get("configuration") == "B"
           else record.get("proposal") if record.get("configuration") == "A"
           else record.get("final_proposal"))
    return Proposal.model_validate(raw) if raw is not None else None


def preview(root: Path, record: dict, *, initial: bool = False):
    """Recompute a run proposal against the active immutable scenario."""
    scenario = load_scenario(root / "data" / "scenarios" / f"{record['scenario_id']}.json")
    selected = proposal(record, initial=initial)
    if selected is None:
        return scenario, None, None
    events, validation = simulate(scenario, selected)
    return scenario, events, validation


def status_matrix(root: Path) -> list[dict]:
    all_runs = runs(root)
    rows = []
    for sid in PILOT_SCENARIO_IDS:
        relevant = [item for item in all_runs if item["scenario_id"] == sid]
        rows.append({"scenario_id": sid,
                     "A": [item for item in relevant if item["configuration"] == "A"],
                     "B": [item for item in relevant if item["configuration"] == "B"]})
    return rows
