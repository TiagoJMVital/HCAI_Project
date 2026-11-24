"""Technical completion contract for publishable experiment runs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from models import (CurrentCriticEvaluation, PlausibilityCriticEvaluation,
                    Proposal)


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


TECHNICAL_ERROR_FIELDS = (
    "error", "error_stage", "failed_llm_outputs", "llm_diagnostics",
    "rate_limit_diagnostics",
)


def completed_b_integrity_issues(record: dict) -> list[str]:
    """Return content-level defects that make a B record non-terminal.

    A top-level scientific status is necessary but not sufficient. This audit
    deliberately distinguishes recovered structured-output retries stored on an
    iteration from an unrecovered technical error stored at record level.
    """
    issues: list[str] = []
    if record.get("configuration") != "B":
        issues.append("configuration is not B")
    if record.get("status") not in B_COMPLETED_STATUSES:
        issues.append("status is not a completed scientific B status")
    for field in TECHNICAL_ERROR_FIELDS:
        if record.get(field):
            issues.append(f"terminal record contains technical error field: {field}")

    iterations = record.get("iterations")
    if not isinstance(iterations, list) or not iterations:
        return issues + ["completed B record has no iterations"]
    settings = record.get("critic_settings")
    max_refinements = settings.get("max_refinements") if isinstance(settings, dict) else None
    if not isinstance(max_refinements, int) or max_refinements < 0:
        issues.append("critic max_refinements is missing or invalid")
    if len(iterations) > (max_refinements + 1 if isinstance(max_refinements, int) else 0):
        issues.append("iteration count exceeds the Critic revision budget")

    for index, item in enumerate(iterations):
        if not isinstance(item, dict) or item.get("index") != index:
            issues.append(f"iteration {index} has an invalid index or shape")
            continue
        raw_proposal = item.get("proposal")
        try:
            proposal = Proposal.model_validate(raw_proposal)
        except Exception:
            issues.append(f"iteration {index} has no complete structured proposal")
            continue
        validation = item.get("validation")
        if not isinstance(validation, dict):
            issues.append(f"iteration {index} has no deterministic validation report")
            continue
        violations = validation.get("violations")
        valid = validation.get("valid")
        if not isinstance(violations, list) or not isinstance(valid, bool) or valid != (not violations):
            issues.append(f"iteration {index} has an inconsistent validation result")
            continue
        if valid:
            if not isinstance(item.get("result_calendar"), dict):
                issues.append(f"iteration {index} is valid but has no result calendar")
            raw_evaluation = item.get("critic_evaluation")
            if not isinstance(raw_evaluation, dict):
                issues.append(f"iteration {index} is valid but has no Critic evaluation")
            else:
                policy_version = record.get("critic_policy_version")
                contract = (CurrentCriticEvaluation
                            if policy_version == "uncertainty_review_v2"
                            else PlausibilityCriticEvaluation)
                try:
                    evaluation = contract.model_validate(
                        {key: value for key, value in raw_evaluation.items()
                         if key != "overall"})
                except Exception:
                    issues.append(f"iteration {index} has an invalid Critic evaluation")
                else:
                    if raw_evaluation.get("overall") != evaluation.overall:
                        issues.append(f"iteration {index} has an inconsistent Critic score")
            policy = item.get("acceptance_policy")
            if not isinstance(policy, dict) or not isinstance(policy.get("accepted"), bool):
                issues.append(f"iteration {index} is valid but has no Critic acceptance policy")
        else:
            if item.get("result_calendar") is not None:
                issues.append(f"iteration {index} is invalid but contains a result calendar")
            if item.get("critic_evaluation") is not None or item.get("acceptance_policy") is not None:
                issues.append(f"iteration {index} is invalid but contains a Critic outcome")

    if record.get("initial_proposal") != iterations[0].get("proposal"):
        issues.append("initial proposal differs from iteration 0")
    last_proposal = next((item.get("proposal") for item in reversed(iterations)
                          if isinstance(item, dict) and item.get("proposal") is not None), None)
    if record.get("final_proposal") != last_proposal:
        issues.append("final proposal differs from the last completed iteration")
    try:
        Proposal.model_validate(record.get("final_proposal"))
    except Exception:
        issues.append("final proposal is not a complete structured proposal")
    if record.get("refinements") != iterations[-1].get("index"):
        issues.append("refinement count differs from the final iteration index")

    status = record.get("status")
    last = iterations[-1]
    validation = last.get("validation") if isinstance(last, dict) else None
    last_valid = validation.get("valid") if isinstance(validation, dict) else None
    policy = last.get("acceptance_policy") if isinstance(last, dict) else None
    if status == "deferred_invalid_proposal":
        if last_valid is not False or not validation.get("violations"):
            issues.append("deferred_invalid_proposal lacks final deterministic violations")
        if isinstance(max_refinements, int) and last.get("index") != max_refinements:
            issues.append("invalid proposal ended before exhausting the revision budget")
        if record.get("critic_accepted") is not False:
            issues.append("invalid proposal is marked Critic-accepted")
    elif status == "deferred_critic_threshold":
        if last_valid is not True:
            issues.append("deferred_critic_threshold lacks a valid final proposal")
        if not isinstance(policy, dict) or policy.get("accepted") is not False:
            issues.append("deferred_critic_threshold lacks a rejecting Critic policy")
        if isinstance(policy, dict) and not policy.get("revision_causes"):
            issues.append("deferred_critic_threshold has no scientific revision cause")
        if not isinstance(record.get("final_score"), (int, float)):
            issues.append("deferred_critic_threshold has no numeric final Critic score")
        elif isinstance(last.get("critic_evaluation"), dict) and (
                record.get("final_score") != last["critic_evaluation"].get("overall")):
            issues.append("final Critic score differs from the final evaluation")
        if isinstance(max_refinements, int) and last.get("index") != max_refinements:
            issues.append("Critic threshold result ended before exhausting the revision budget")
        if record.get("critic_accepted") is not False:
            issues.append("threshold-deferred proposal is marked Critic-accepted")
    elif status == "proposal_ready":
        if last_valid is not True:
            issues.append("proposal_ready lacks a valid final proposal")
        if not isinstance(policy, dict) or policy.get("accepted") is not True:
            issues.append("proposal_ready lacks an accepting Critic policy")
        if record.get("critic_accepted") is not True:
            issues.append("proposal_ready is not marked Critic-accepted")
        if isinstance(last.get("critic_evaluation"), dict) and (
                record.get("final_score") != last["critic_evaluation"].get("overall")):
            issues.append("final Critic score differs from the final evaluation")
    return issues


def validate_completed_b_integrity(record: dict) -> None:
    issues = completed_b_integrity_issues(record)
    if issues:
        raise ValueError("incomplete or inconsistent B execution: " + "; ".join(issues))


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
    if configuration == "B":
        try:
            validate_completed_b_integrity(record)
        except ValueError as exc:
            raise TechnicalRunError(record.get("scenario_id", "unknown"), record | {
                "status": "serialization_error", "error_stage": "completion_validation",
                "error": str(exc), "safe_action": "no_autonomous_action",
            }) from None


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
    validate_completed_b_integrity(record)


def technical_failure_path(root: Path, record: dict) -> Path:
    """Location outside active runs for an immutable failed-attempt checkpoint."""
    scenario_id = str(record.get("scenario_id") or "unknown")
    run_id = str(record.get("run_id") or "unknown")
    if (Path(scenario_id).name != scenario_id or Path(run_id).name != run_id
            or scenario_id in {".", ".."} or run_id in {".", ".."}):
        raise ValueError("unsafe technical failure identity")
    return (root / "eval" / "technical_failures" / scenario_id / run_id / "B"
            / f"{scenario_id}.json")


def archive_technical_failure(root: Path, record: dict) -> Path:
    """Persist raw model output and diagnostics without making a discoverable run."""
    from benchmark_v2 import atomic_json
    target = technical_failure_path(root, record)
    payload = dict(record) | {"artifact_type": "technical_failure",
                              "active_run": False}
    if target.exists():
        if json.loads(target.read_text(encoding="utf-8")) != payload:
            raise ValueError(f"technical failure identity collision: {target}")
        return target
    atomic_json(target, payload)
    return target


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
