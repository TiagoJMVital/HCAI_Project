"""Technical completion contract for publishable experiment runs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


A_COMPLETED_STATUSES = {"proposal_ready", "invalid_proposal"}
B_COMPLETED_STATUSES = {
    "proposal_ready", "deferred_invalid_proposal", "deferred_critic_threshold",
}


class TechnicalRunError(RuntimeError):
    def __init__(self, scenario_id: str, record: dict):
        self.scenario_id = scenario_id
        self.record = record
        stage = record.get("error_stage") or "runner"
        status = record.get("status") or "technical_error"
        message = record.get("error") or "technical execution did not complete"
        super().__init__(f"{scenario_id}: {status} at {stage}: {message}")


def validate_completed_record(record: dict, configuration: str) -> None:
    statuses = A_COMPLETED_STATUSES if configuration == "A" else B_COMPLETED_STATUSES
    if record.get("configuration") != configuration or record.get("status") not in statuses:
        raise TechnicalRunError(str(record.get("scenario_id") or "unknown"), record)
    required = {"schema_version", "scenario_id", "run_id", "configuration", "status",
                "scenario_sha256", "generated_at", "prompt_versions"}
    if configuration == "B":
        required |= {"iterations", "initial_proposal", "final_proposal", "critic_settings",
                     "result_calendar_version", "simulator_version", "dataset_manifest_sha256"}
        iterations = record.get("iterations")
        if not isinstance(iterations, list) or not iterations:
            raise TechnicalRunError(record["scenario_id"], record | {
                "status": "serialization_error", "error": "completed B run has no iterations"})
    missing = sorted(field for field in required if record.get(field) is None)
    if missing:
        raise TechnicalRunError(record.get("scenario_id", "unknown"), record | {
            "status": "serialization_error",
            "error": "completed run missing fields: " + ", ".join(missing),
        })


def validate_historical_pilot_b_record(record: dict) -> None:
    """Validate a terminal pilot B record without requiring later provenance fields."""
    if record.get("schema_version") != "2.0" or record.get("configuration") != "B":
        raise ValueError("historical pilot artifact is not a schema-2 configuration-B run")
    if record.get("status") not in B_COMPLETED_STATUSES:
        raise ValueError("historical pilot B artifact is not technically terminal")
    required = {
        "scenario_id", "run_id", "family", "profile_id", "split", "generated_at",
        "prompt_versions", "iterations", "initial_proposal", "final_proposal",
        "critic_settings",
    }
    missing = sorted(field for field in required if record.get(field) is None)
    if missing:
        raise ValueError("historical pilot B artifact is incomplete: " + ", ".join(missing))
    if record["split"] != "train":
        raise ValueError("historical pilot B artifact is not in the training split")
    if not isinstance(record["iterations"], list) or not record["iterations"]:
        raise ValueError("historical pilot B artifact has no completed iterations")


def historical_pilot_completed_b(root: Path) -> dict[str, dict]:
    """Return manifest-authenticated terminal B pilot runs keyed by scenario ID.

    The migration manifest is the source of truth. Every selected destination is
    checked against its recorded SHA-256 and its immutable JSON identity before it
    can suppress a resumed execution.
    """
    root = root.resolve()
    manifest_path = root / "eval" / "dataset_layout_migration_manifest.json"
    if not manifest_path.is_file():
        return {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid dataset layout migration manifest: {exc}") from exc
    if manifest.get("schema_version") != "1.0" or not isinstance(manifest.get("moves"), list):
        raise ValueError("unexpected dataset layout migration manifest contract")

    completed: dict[str, dict] = {}
    for move in manifest["moves"]:
        if move.get("configuration") != "B":
            continue
        relative = Path(str(move.get("destination") or ""))
        if (relative.is_absolute() or ".." in relative.parts
                or relative.parts[:3] != ("eval", "runs", "treino")):
            raise ValueError(f"unsafe historical pilot destination: {relative}")
        path = (root / relative).resolve()
        try:
            path.relative_to(root / "eval" / "runs" / "treino")
        except ValueError as exc:
            raise ValueError(f"historical pilot destination escapes training runs: {relative}") from exc
        if not path.is_file():
            raise ValueError(f"missing historical pilot artifact: {relative}")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != move.get("sha256"):
            raise ValueError(f"historical pilot artifact hash mismatch: {relative}")
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid historical pilot artifact: {relative}") from exc
        validate_historical_pilot_b_record(record)
        for field in ("scenario_id", "run_id", "configuration", "status"):
            if record.get(field) != move.get(field):
                raise ValueError(f"historical pilot manifest identity mismatch: {relative}")
        scenario_id = record["scenario_id"]
        if scenario_id in completed:
            raise ValueError(f"duplicate historical pilot B scenario: {scenario_id}")
        completed[scenario_id] = record | {
            "_path": str(relative), "_completion_source": "historical_pilot_manifest"}
    return completed


def publish_completed_record(target: Path, record: dict, *, runs_root: Path) -> None:
    """Atomically publish once; clean empty directories after write failure."""
    from benchmark_v2 import atomic_json
    if target.exists():
        raise FileExistsError(f"run destination already exists: {target}")
    try:
        atomic_json(target, record)
    except Exception:
        current = target.parent
        while current != runs_root and current.exists():
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
        raise
