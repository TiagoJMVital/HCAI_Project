"""Technical completion contract for publishable experiment runs."""
from __future__ import annotations

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
