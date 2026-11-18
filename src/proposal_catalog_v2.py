"""Immutable v2 proposal artifacts imported from explicit B runs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from benchmark_v2 import atomic_json
from calendar_v2 import simulate
from critic import final_calendar_view
from models import CurrentCriticEvaluation, Proposal
from scenario_v2 import load_manifest, load_scenario

ROOT = Path(__file__).resolve().parent.parent


def catalog(root: Path) -> list[dict]:
    rows = []
    manifest = {row["scenario_id"]: row for row in load_manifest(root)}
    for path in sorted((root / "data" / "proposals").glob("*.json")):
        artifact = json.loads(path.read_text(encoding="utf-8"))
        if artifact["proposal_id"] != path.stem or artifact["scenario_id"] not in manifest:
            raise ValueError(f"invalid v2 catalog item: {path.name}")
        row = manifest[artifact["scenario_id"]]
        if any(artifact[key] != row[key] for key in ("family_id", "profile_id", "split")):
            raise ValueError(f"manifest provenance mismatch: {path.name}")
        Proposal.model_validate(artifact["final_proposal"])
        identity = {"scenario_id": artifact["scenario_id"], "run_id": artifact["run_id"],
                    "proposal": artifact["final_proposal"]}
        expected = "v2p_" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
        if expected != path.stem:
            raise ValueError(f"proposal identity mismatch: {path.name}")
        rows.append(artifact)
    return rows


def import_result(root: Path, result_path: Path) -> Path:
    record = json.loads(result_path.read_text(encoding="utf-8"))
    if record.get("schema_version") != "2.0" or record.get("configuration") != "B":
        raise ValueError("a v2 B run is required")
    if not isinstance(record.get("iterations"), list) or not record["iterations"]:
        raise ValueError("missing B refinement history")
    proposal = Proposal.model_validate(record.get("final_proposal"))
    last = next((item for item in reversed(record["iterations"]) if item.get("proposal") is not None), None)
    if last is None or Proposal.model_validate(last["proposal"]) != proposal:
        raise ValueError("final proposal disagrees with refinement history")
    manifest = {row["scenario_id"]: row for row in load_manifest(root)}
    sid = record["scenario_id"]
    row = manifest.get(sid)
    if row is None or any(record.get(key) != row[key] for key in ("profile_id", "split")) or record.get("family") != row["family_id"]:
        raise ValueError("result provenance differs from imported scenario")
    scenario = load_scenario(root / "data" / "scenarios" / f"{sid}.json")
    _, validation = simulate(scenario, proposal)
    # New outcome-aware runs carry optional calendars. Recompute them from the
    # imported scenario and each structured proposal before trusting the audit
    # trail. Older runs have no such fields and remain unchanged.
    original_ids = {event.id for event in scenario.calendar.events}
    for step in record["iterations"]:
        if record.get("critic_policy_version") == "plausibility_review_v1" and step.get("critic_evaluation") is not None:
            raw_evaluation = {k: v for k, v in step["critic_evaluation"].items() if k != "overall"}
            current = CurrentCriticEvaluation.model_validate(raw_evaluation)
            policy = step.get("acceptance_policy")
            if not isinstance(policy, dict) or policy.get("plausibility_revision_required") != current.plausibility_review.revision_required:
                raise ValueError("new Critic result missing or inconsistent acceptance policy")
        if step.get("result_calendar") is None:
            if record.get("critic_input_version") == "final_calendar_v1" and step.get("critic_evaluation") is not None:
                raise ValueError("Critic evaluation missing its result calendar")
            continue
        step_proposal = Proposal.model_validate(step["proposal"])
        step_events, step_validation = simulate(scenario, step_proposal)
        if step_events is None or not step_validation["valid"] or step["result_calendar"] != final_calendar_view(
                step_events, step_proposal, original_ids=original_ids,
                timezone=scenario.profile.timezone):
            raise ValueError("iteration result calendar differs from deterministic simulation")
    if (record.get("critic_input_version") == "final_calendar_v1"
            and record.get("status") == "proposal_ready" and record.get("final_result_calendar") is None):
        raise ValueError("accepted proposal missing its final result calendar")
    if record.get("final_result_calendar") is not None:
        final_events, final_validation = simulate(scenario, proposal)
        if final_events is None or not final_validation["valid"] or record["final_result_calendar"] != final_calendar_view(
                final_events, proposal, original_ids=original_ids,
                timezone=scenario.profile.timezone):
            raise ValueError("final result calendar differs from deterministic simulation")
    identity = {"scenario_id": sid, "run_id": record["run_id"], "proposal": proposal.model_dump()}
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
                "final_proposal": proposal.model_dump(), "technical_validation": validation,
                "source_result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest()}
    # Optional audit data for runs using outcome-aware critique. Historical
    # artifacts remain byte-compatible when their source result lacks it.
    for field in ("critic_input_version", "critic_policy_version", "final_result_calendar", "replay_source",
                  "unresolved_critic_weaknesses", "unresolved_plausibility_review"):
        if field in record:
            artifact[field] = record[field]
    target = root / "data" / "proposals" / f"{pid}.json"
    if target.exists():
        if json.loads(target.read_text(encoding="utf-8")) != artifact:
            raise ValueError("proposal identity collision or changed source")
        return target
    atomic_json(target, artifact)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Import an existing B v2 result; no LLM call")
    parser.add_argument("result", type=Path)
    args = parser.parse_args()
    print(import_result(ROOT, args.result))


if __name__ == "__main__":
    main()
