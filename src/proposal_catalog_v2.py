"""Immutable v2 proposal artifacts imported from explicit B runs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from benchmark_v2 import atomic_json
from calendar_v2 import simulate
from critic import LEGACY_RESULT_CALENDAR_VERSION, final_calendar_view
from models import CurrentCriticEvaluation, PlausibilityCriticEvaluation, Proposal
from run_catalog_v2 import runs
from run_completion_v2 import (B_COMPLETED_STATUSES, completed_b_integrity_issues,
                               validate_completed_b_integrity)
from scenario_v2 import confirmed_changes_fingerprint, load_manifest, load_scenario
from final_dataset_v2 import combined_manifest, final_manifest, manifest_path, scenario_path

ROOT = Path(__file__).resolve().parent.parent


def _canonical_validation(report: dict) -> dict:
    """Normalize semantically unordered diagnostics for stable imports."""
    normalized = dict(report)
    if isinstance(normalized.get("warnings"), list):
        normalized["warnings"] = sorted(normalized["warnings"])
    return normalized


def catalog(root: Path) -> list[dict]:
    rows = []
    manifest = {row["scenario_id"]: row for row in combined_manifest(root)}
    for path in sorted((root / "data" / "proposals").glob("*.json")):
        artifact = json.loads(path.read_text(encoding="utf-8"))
        if artifact["proposal_id"] != path.stem or artifact["scenario_id"] not in manifest:
            raise ValueError(f"invalid v2 catalog item: {path.name}")
        row = manifest[artifact["scenario_id"]]
        if any(artifact[key] != row[key] for key in ("family_id", "profile_id", "split")):
            raise ValueError(f"manifest provenance mismatch: {path.name}")
        scenario = load_scenario(Path(row["scenario_path"]))
        if scenario.confirmed_changes and artifact.get("confirmed_changes_sha256") != confirmed_changes_fingerprint(scenario):
            raise ValueError(f"confirmed-change provenance mismatch: {path.name}")
        if scenario.aggregate_requirements:
            aggregate_hash = hashlib.sha256(json.dumps(
                [item.model_dump(mode="json") for item in scenario.aggregate_requirements],
                sort_keys=True).encode()).hexdigest()
            if artifact.get("aggregate_requirements_sha256") != aggregate_hash:
                raise ValueError(f"aggregate provenance mismatch: {path.name}")
        Proposal.model_validate(artifact["final_proposal"])
        identity = {"scenario_id": artifact["scenario_id"], "run_id": artifact["run_id"],
                    "proposal": artifact["final_proposal"]}
        expected = "v2p_" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
        if expected != path.stem:
            raise ValueError(f"proposal identity mismatch: {path.name}")
        rows.append(artifact)
    return rows


def training_catalog_audit(root: Path) -> dict:
    """Separate active training proposals from preserved but ineligible imports."""
    manifest_rows = (final_manifest(root) if manifest_path(root).is_file()
                     else combined_manifest(root))
    training_ids = {row["scenario_id"] for row in manifest_rows if row["split"] == "train"}
    source_runs = {(record["scenario_id"], record["run_id"]): record
                   for record in runs(root, configuration="B")}
    selected = []
    quarantined = []
    for artifact in catalog(root):
        if artifact["scenario_id"] not in training_ids:
            continue
        source = source_runs.get((artifact["scenario_id"], artifact["run_id"]))
        reasons = []
        if source is None:
            reasons.append("source run is not discoverable")
        else:
            reasons.extend(completed_b_integrity_issues(source))
            source_path = root / source["_path"]
            if hashlib.sha256(source_path.read_bytes()).hexdigest() != artifact.get("source_result_sha256"):
                reasons.append("source run hash differs from imported proposal provenance")
        if reasons:
            quarantined.append({"proposal_id": artifact["proposal_id"],
                                "scenario_id": artifact["scenario_id"],
                                "run_id": artifact["run_id"], "reasons": reasons})
        else:
            selected.append(artifact)
    duplicates = {scenario_id for scenario_id in training_ids
                  if sum(row["scenario_id"] == scenario_id for row in selected) > 1}
    if duplicates:
        raise ValueError("multiple imported canonical training proposals: "
                         + ", ".join(sorted(duplicates)))
    return {"active": sorted(selected, key=lambda row: (row["family_id"], row["scenario_id"])),
            "quarantined": sorted(quarantined, key=lambda row: (row["scenario_id"], row["run_id"]))}


def training_catalog(root: Path) -> list[dict]:
    """One integrity-verified canonical proposal per authoritative training scenario."""
    return training_catalog_audit(root)["active"]


def canonical_training_results(root: Path) -> dict[str, dict]:
    """Select canonical B results without using Critic score or autonomy outcome.

    An already imported proposal is immutable and remains canonical. For a scenario
    not yet imported, choose the earliest technically terminal B run by generation
    time and run ID. Scientific terminal outcomes remain eligible for scheduling-
    acceptability review when their final proposal is structurally complete.
    """
    manifest_rows = (final_manifest(root) if manifest_path(root).is_file()
                     else combined_manifest(root))
    training = {row["scenario_id"]: row for row in manifest_rows if row["split"] == "train"}
    imported = {row["scenario_id"]: row for row in training_catalog(root)}
    candidates: dict[str, list[dict]] = {scenario_id: [] for scenario_id in training}
    for record in runs(root, configuration="B"):
        if (record["scenario_id"] in training
                and record.get("status") in B_COMPLETED_STATUSES
                and record.get("final_proposal") is not None
                and not completed_b_integrity_issues(record)):
            candidates[record["scenario_id"]].append(record)
    selected = {}
    for scenario_id, records in candidates.items():
        if not records:
            continue
        if scenario_id in imported:
            run_id = imported[scenario_id]["run_id"]
            match = next((record for record in records if record["run_id"] == run_id), None)
            if match is None:
                raise ValueError(f"imported canonical proposal has no source run: {scenario_id}")
            selected[scenario_id] = match
            continue
        selected[scenario_id] = min(
            records, key=lambda record: (record.get("generated_at") or "", record["run_id"]))
    return selected


def import_training_results(root: Path) -> dict:
    """Idempotently import every currently eligible canonical training B result."""
    initial_audit = training_catalog_audit(root)
    before = {row["scenario_id"]: row for row in initial_audit["active"]}
    selected = canonical_training_results(root)
    imported_paths = []
    preserved = []
    for scenario_id in sorted(selected):
        if scenario_id in before:
            preserved.append(before[scenario_id]["proposal_id"])
            continue
        record = selected[scenario_id]
        imported_paths.append(str(import_result(root, root / record["_path"])))
    final_audit = training_catalog_audit(root)
    return {
        "eligible_results": len(selected),
        "previously_imported": len(preserved),
        "newly_imported": len(imported_paths),
        "total_training_proposals": len(final_audit["active"]),
        "quarantined_proposals": final_audit["quarantined"],
        "preserved_proposal_ids": preserved,
        "imported_paths": imported_paths,
    }


def import_result(root: Path, result_path: Path) -> Path:
    record = json.loads(result_path.read_text(encoding="utf-8"))
    if record.get("schema_version") != "2.0" or record.get("configuration") != "B":
        raise ValueError("a v2 B run is required")
    validate_completed_b_integrity(record)
    if not isinstance(record.get("iterations"), list) or not record["iterations"]:
        raise ValueError("missing B refinement history")
    proposal = Proposal.model_validate(record.get("final_proposal"))
    last = next((item for item in reversed(record["iterations"]) if item.get("proposal") is not None), None)
    if last is None or Proposal.model_validate(last["proposal"]) != proposal:
        raise ValueError("final proposal disagrees with refinement history")
    manifest = {row["scenario_id"]: row for row in combined_manifest(root)}
    sid = record["scenario_id"]
    row = manifest.get(sid)
    if row is None or any(record.get(key) != row[key] for key in ("profile_id", "split")) or record.get("family") != row["family_id"]:
        raise ValueError("result provenance differs from imported scenario")
    scenario = load_scenario(scenario_path(root, sid))
    current_aggregate = (hashlib.sha256(json.dumps(
        [rule.model_dump(mode="json") for rule in scenario.aggregate_requirements],
        sort_keys=True).encode()).hexdigest() if scenario.aggregate_requirements else None)
    if scenario.aggregate_requirements and record.get("aggregate_requirements_sha256") != current_aggregate:
        raise ValueError("result was generated with different aggregate requirements")
    if scenario.confirmed_changes and record.get("confirmed_changes_sha256") != confirmed_changes_fingerprint(scenario):
        raise ValueError("result was generated with different confirmed-change authorizations")
    _, validation = simulate(scenario, proposal)
    # New outcome-aware runs carry optional calendars. Recompute them from the
    # imported scenario and each structured proposal before trusting the audit
    # trail. Older runs have no such fields and remain unchanged.
    original_ids = {event.id for event in scenario.calendar.events}
    policy_version = record.get("critic_policy_version")
    history = []
    for step in record["iterations"]:
        if policy_version in {"plausibility_review_v1", "uncertainty_review_v2"} and step.get("critic_evaluation") is not None:
            raw_evaluation = {k: v for k, v in step["critic_evaluation"].items() if k != "overall"}
            contract = (CurrentCriticEvaluation if policy_version == "uncertainty_review_v2"
                        else PlausibilityCriticEvaluation)
            current = contract.model_validate(raw_evaluation)
            policy = step.get("acceptance_policy")
            if not isinstance(policy, dict) or policy.get("plausibility_revision_required") != current.plausibility_review.revision_required:
                raise ValueError("new Critic result missing or inconsistent acceptance policy")
            if policy_version == "uncertainty_review_v2":
                assumptions = [entry.model_dump() for entry in current.unresolved_assumptions]
                if step.get("unresolved_assumptions") != assumptions:
                    raise ValueError("iteration uncertainty summary differs from Critic response")
                history.append({"iteration": step["index"], "unresolved_assumptions": assumptions})
        if step.get("result_calendar") is None:
            if record.get("critic_input_version") == "final_calendar_v1" and step.get("critic_evaluation") is not None:
                raise ValueError("Critic evaluation missing its result calendar")
            continue
        step_proposal = Proposal.model_validate(step["proposal"])
        step_events, step_validation = simulate(scenario, step_proposal)
        calendar_version = record.get("result_calendar_version", LEGACY_RESULT_CALENDAR_VERSION)
        if step_events is None or not step_validation["valid"] or step["result_calendar"] != final_calendar_view(
                step_events, step_proposal, original_ids=original_ids,
                timezone=scenario.profile.timezone, version=calendar_version):
            raise ValueError("iteration result calendar differs from deterministic simulation")
    if policy_version == "uncertainty_review_v2":
        if record.get("uncertainty_history") != history:
            raise ValueError("uncertainty history differs from Critic iterations")
        last_review = record["iterations"][-1].get("critic_evaluation")
        expected_final = (last_review["unresolved_assumptions"] if last_review is not None else None)
        if record.get("final_unresolved_assumptions") != expected_final:
            raise ValueError("final uncertainty summary differs from final iteration")
    if (record.get("critic_input_version") == "final_calendar_v1"
            and record.get("status") == "proposal_ready" and record.get("final_result_calendar") is None):
        raise ValueError("accepted proposal missing its final result calendar")
    if record.get("final_result_calendar") is not None:
        final_events, final_validation = simulate(scenario, proposal)
        if final_events is None or not final_validation["valid"] or record["final_result_calendar"] != final_calendar_view(
                final_events, proposal, original_ids=original_ids,
                timezone=scenario.profile.timezone,
                version=record.get("result_calendar_version", LEGACY_RESULT_CALENDAR_VERSION)):
            raise ValueError("final result calendar differs from deterministic simulation")
    identity = {"scenario_id": sid, "run_id": record["run_id"], "proposal": record["final_proposal"]}
    pid = "v2p_" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
    artifact = {"proposal_id": pid, "scenario_id": sid, "family_id": row["family_id"],
                "profile_id": row["profile_id"], "split": row["split"],
                "run_id": record["run_id"], "configuration": "B",
                "generated_at": record.get("generated_at"),
                "proposer_provider": record.get("proposer_provider"),
                "proposer_model": record.get("proposer_model"),
                "proposer_generation_config": record.get("proposer_generation_config"),
                "critic_provider": record.get("critic_provider"),
                "critic_model": record.get("critic_model"),
                "critic_generation_config": record.get("critic_generation_config"),
                "prompt_versions": record.get("prompt_versions"),
                "critic_settings": record.get("critic_settings"),
                "experiment_id": record.get("experiment_id"),
                "repeat_index": record.get("repeat_index"),
                "seconds": record.get("seconds"),
                "critic_score": record.get("final_score"),
                "critic_accepted": record.get("critic_accepted"),
                "iterations": record["iterations"], "refinements": record.get("refinements"),
                "source_status": record.get("status"),
                "final_proposal": record["final_proposal"],
                "technical_validation": _canonical_validation(validation),
                "source_result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest()}
    if "scenario_sha256" in record:
        artifact["scenario_sha256"] = record["scenario_sha256"]
    if "aggregate_requirements_sha256" in record:
        artifact["aggregate_requirements_sha256"] = record["aggregate_requirements_sha256"]
    if "confirmed_changes_sha256" in record:
        artifact["confirmed_changes_sha256"] = record["confirmed_changes_sha256"]
    # Optional audit data for runs using outcome-aware critique. Historical
    # artifacts remain byte-compatible when their source result lacks it.
    for field in ("critic_input_version", "critic_policy_version", "result_calendar_version",
                  "final_result_calendar", "replay_source",
                  "final_unresolved_assumptions", "uncertainty_history",
                  "unresolved_critic_weaknesses", "unresolved_plausibility_review"):
        if field in record:
            artifact[field] = record[field]
    target = root / "data" / "proposals" / f"{pid}.json"
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        comparable = dict(existing)
        if isinstance(comparable.get("technical_validation"), dict):
            comparable["technical_validation"] = _canonical_validation(
                comparable["technical_validation"])
        if comparable != artifact:
            raise ValueError("proposal identity collision or changed source")
        if existing != artifact:
            atomic_json(target, artifact)
        return target
    atomic_json(target, artifact)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Import an existing B v2 result; no LLM call")
    parser.add_argument("result", type=Path, nargs="?")
    parser.add_argument("--training", action="store_true",
                        help="idempotently import all canonical final training B results")
    args = parser.parse_args()
    if args.training:
        if args.result is not None:
            parser.error("result and --training are mutually exclusive")
        print(json.dumps(import_training_results(ROOT), indent=2, ensure_ascii=False))
    elif args.result is None:
        parser.error("result is required unless --training is used")
    else:
        print(import_result(ROOT, args.result))


if __name__ == "__main__":
    main()
