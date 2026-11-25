"""Sequential, resumable configuration-B executor for final training scenarios."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "eval")]

from benchmark_v2 import atomic_json  # noqa: E402
from calendar_v2 import SIMULATOR_VERSION  # noqa: E402
from critic import CRITIC_POLICY_VERSION, RESULT_CALENDAR_VERSION, SYSTEM as CRITIC_SYSTEM  # noqa: E402
from final_dataset_v2 import (BLOCKED_STATE, ELIGIBLE_STATES, FAMILY_FOLDERS,
                              final_manifest, manifest_sha256)  # noqa: E402
from llm import get_provider  # noqa: E402
from pipeline_b import CriticSettings  # noqa: E402
from proposal_catalog_v2 import import_result  # noqa: E402
from proposer_v2 import (PROPOSER_WIRE_SCHEMA_SHA256, PROPOSER_WIRE_SCHEMA_VERSION,
                         REVISION_GUIDANCE, SYSTEM_V2)  # noqa: E402
from run_catalog_v2 import runs  # noqa: E402
from run_completion_v2 import (B_COMPLETED_STATUSES, TechnicalRunError,
                               archive_technical_failure, completed_b_integrity_issues,
                               historical_pilot_completed_b)  # noqa: E402
from run_config_b_v2 import run_one  # noqa: E402


def expected_prompt_versions() -> dict:
    return {"proposer_sha256": hashlib.sha256(SYSTEM_V2.encode()).hexdigest(),
            "proposer_wire_schema_version": PROPOSER_WIRE_SCHEMA_VERSION,
            "proposer_wire_schema_sha256": PROPOSER_WIRE_SCHEMA_SHA256,
            "proposer_revision_sha256": hashlib.sha256(REVISION_GUIDANCE.encode()).hexdigest(),
            "critic_sha256": hashlib.sha256(CRITIC_SYSTEM.encode()).hexdigest()}


def compatible_completed(root: Path, row: dict, proposer, critic) -> dict | None:
    expected = {
        "schema_version": "2.0", "configuration": "B",
        "scenario_sha256": row["scenario_sha256"],
        "dataset_manifest_sha256": manifest_sha256(root),
        "simulator_version": SIMULATOR_VERSION,
        "result_calendar_version": RESULT_CALENDAR_VERSION,
        "prompt_versions": expected_prompt_versions(),
        "proposer_provider": proposer.name, "proposer_model": proposer.model,
        "critic_provider": critic.name, "critic_model": critic.model,
        "proposer_generation_config": proposer.generation_config(),
        "critic_generation_config": critic.generation_config(),
        "critic_settings": CriticSettings().__dict__,
    }
    for record in runs(root, scenario_id=row["scenario_id"], configuration="B"):
        if record.get("status") not in B_COMPLETED_STATUSES:
            continue
        if completed_b_integrity_issues(record):
            continue
        if all(record.get(field) == value for field, value in expected.items()):
            return record
    return None


def select_rows(rows: list[dict], *, only: str | None = None,
                family: str | None = None) -> list[dict]:
    training = [row for row in rows if row["split"] == "train"]
    if only is not None:
        match = next((row for row in rows if row["scenario_id"] == only), None)
        if match is None:
            raise ValueError(f"unknown final-dataset scenario: {only}")
        if match["split"] != "train":
            raise ValueError("--only cannot select development or test scenarios")
        training = [match]
    if family is not None:
        aliases = {value: key for key, value in FAMILY_FOLDERS.items()}
        family_id = aliases.get(family, family)
        if family_id not in {row["family_id"] for row in training}:
            raise ValueError("--family must identify a selected training family")
        training = [row for row in training if row["family_id"] == family_id]
    return sorted(training, key=lambda row: row["scenario_id"])


def should_stop_batch(error: TechnicalRunError) -> bool:
    record = error.record
    diagnostics = record.get("rate_limit_diagnostics") or record.get("llm_diagnostics") or {}
    status = diagnostics.get("http_status")
    classification = diagnostics.get("classification")
    text = f"{record.get('error', '')} {json.dumps(diagnostics, ensure_ascii=False)}".lower()
    return (bool(record.get("rate_limit_diagnostics")) or status in {401, 403}
            or classification == "output_truncated"
            or any(term in text for term in ("quota", "rate limit", "token", "autentica",
                                             "configuração iaedu", "api key")))


def execute_batch(args, *, execute=run_one) -> tuple[int, dict]:
    rows = final_manifest(ROOT, validate_scenarios=True)
    selected = select_rows(rows, only=args.only, family=args.family)
    proposer = get_provider(role="PROPOSER", provider="iaedu")
    critic = get_provider(role="CRITIC", provider="iaedu")
    print("Final dataset: 60 train / 10 dev / 30 test; configuration B only", flush=True)
    print("Proposer generation config:", json.dumps(proposer.generation_config(), sort_keys=True), flush=True)
    print("Critic generation config:", json.dumps(critic.generation_config(), sort_keys=True), flush=True)
    print("Critic settings:", json.dumps(CriticSettings().__dict__, sort_keys=True), flush=True)

    blocked = [row for row in selected if row["state"] == BLOCKED_STATE]
    eligible = [row for row in selected if row["state"] in ELIGIBLE_STATES]
    unknown = [row for row in selected if row["state"] not in ELIGIBLE_STATES | {BLOCKED_STATE}]
    if unknown:
        raise ValueError("unrecognized readiness states: " + ", ".join(row["scenario_id"] for row in unknown))
    completed: dict[str, dict] = {}
    completed_current: set[str] = set()
    completed_pilot: set[str] = set()
    if not args.force:
        pilot = historical_pilot_completed_b(ROOT)
        for row in eligible:
            if row["scenario_id"] in pilot:
                pilot_record = pilot[row["scenario_id"]]
                if (pilot_record.get("family") != row["family_id"]
                        or pilot_record.get("profile_id") != row["profile_id"]
                        or pilot_record.get("split") != row["split"]):
                    raise ValueError(
                        f"historical pilot/current manifest mismatch: {row['scenario_id']}")
                completed[row["scenario_id"]] = pilot_record
                completed_pilot.add(row["scenario_id"])
                continue
            match = compatible_completed(ROOT, row, proposer, critic)
            if match is not None:
                completed[row["scenario_id"]] = match
                completed_current.add(row["scenario_id"])
    pending = [row for row in eligible if row["scenario_id"] not in completed]
    if args.limit is not None:
        pending = pending[:args.limit]

    for row in blocked:
        print(f"BLOCKED — {row['scenario_id']} — {row['state_reason']}", flush=True)
    for sid, record in sorted(completed.items()):
        if sid in completed_pilot:
            print(f"ALREADY_COMPLETED_PILOT — {sid} — {record['run_id']}", flush=True)
        else:
            print(f"SKIPPED — already completed — {sid} — {record['run_id']}", flush=True)
    for row in pending:
        print(f"{'WOULD RUN' if args.dry_run else 'PENDING'} — {row['scenario_id']}", flush=True)

    summary = {"generated_at": datetime.now(timezone.utc).isoformat(),
               "dry_run": args.dry_run, "selected": len(selected),
               "eligible": len(eligible), "blocked": len(blocked),
               "already_completed_total": len(completed),
               "already_completed_compatible": len(completed_current),
               "already_completed_current": len(completed_current),
               "already_completed_pilot": len(completed_pilot),
               "pending_selected": len(pending), "succeeded": [], "failed": [],
               "imported_proposals": [], "import_failures": [],
               "stopped_early": False}
    if args.dry_run:
        atomic_json(ROOT / "eval" / "training_b_last_summary.json", summary)
        return 0, summary

    for index, row in enumerate(pending, 1):
        if index > 1 and args.delay:
            print(f"PACING — waiting {args.delay}s", flush=True)
            time.sleep(args.delay)
        sid = row["scenario_id"]
        print(f"RUNNING {index}/{len(pending)} — {sid}", flush=True)
        try:
            path = execute(
                ROOT, sid, proposer, critic, CriticSettings(), manifest_row=row,
                scenario_path=Path(row["scenario_path"]),
                dataset_manifest_sha256=manifest_sha256(ROOT))
        except TechnicalRunError as exc:
            record = exc.record
            failure_path = archive_technical_failure(ROOT, record)
            failure = {"scenario_id": sid, "status": record.get("status"),
                       "run_id": record.get("run_id"),
                       "stage": record.get("error_stage"), "message": record.get("error"),
                       "classification": (record.get("rate_limit_diagnostics") or
                                          record.get("llm_diagnostics") or {}).get("classification"),
                       "diagnostics": (record.get("rate_limit_diagnostics") or
                                       record.get("llm_diagnostics") or {}),
                       "recoverable_intermediate": bool(
                           record.get("initial_proposal") and record.get("iterations")),
                       "technical_artifact": str(failure_path.relative_to(ROOT))}
            summary["failed"].append(failure)
            print(f"FAILED — {sid} — {failure['stage']}: {failure['message']}", flush=True)
            if should_stop_batch(exc):
                summary["stopped_early"] = True
                print("STOPPED — provider authentication/quota/rate/token failure; resume later", flush=True)
                break
            continue
        success = {"scenario_id": sid, "path": str(path.relative_to(ROOT))}
        summary["succeeded"].append(success)
        print(f"COMPLETED — {sid} — {path}", flush=True)
        try:
            proposal_path = import_result(ROOT, path)
        except (ValueError, OSError) as exc:
            failure = {"scenario_id": sid, "path": success["path"], "message": str(exc)}
            summary["import_failures"].append(failure)
            print(f"IMPORT FAILED — {sid} — {exc}", flush=True)
        else:
            imported = str(proposal_path.relative_to(ROOT))
            summary["imported_proposals"].append(
                {"scenario_id": sid, "path": imported})
            print(f"IMPORTED — {sid} — {proposal_path}", flush=True)
    atomic_json(ROOT / "eval" / "training_b_last_summary.json", summary)
    return (2 if summary["stopped_early"] else
            1 if summary["failed"] or summary["import_failures"] else 0), summary


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--dry-run", action="store_true", help="list work without provider calls")
    result.add_argument("--resume", action="store_true", help="explicitly request the default skip-completed behavior")
    result.add_argument("--force", action="store_true", help="deliberately run even when a compatible result exists")
    result.add_argument("--only", help="one training scenario ID")
    result.add_argument("--family", help="training family ID or configured folder alias")
    result.add_argument("--limit", type=int, help="maximum pending scenarios to execute")
    result.add_argument("--delay", type=int, default=int(os.getenv("PILOT_REQUEST_DELAY_SECONDS", "60")),
                        help="seconds between scenarios (default: pilot pacing setting, 60)")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.force and args.resume:
        parser().error("--force and --resume are mutually exclusive")
    if args.limit is not None and args.limit < 1:
        parser().error("--limit must be at least 1")
    if args.delay < 0:
        parser().error("--delay must be non-negative")
    try:
        code, _ = execute_batch(args)
        return code
    except (ValueError, OSError) as exc:
        print(f"PRECHECK FAILED — {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
