"""Migrate publishable pilot runs to split/family/scenario storage."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from benchmark_v2 import atomic_json  # noqa: E402
from final_dataset_v2 import final_manifest  # noqa: E402
from run_completion_v2 import A_COMPLETED_STATUSES, B_COMPLETED_STATUSES  # noqa: E402
from run_paths_v2 import discover_result_paths, path_identity, run_result_path  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_plan(root: Path) -> dict:
    manifest = {row["scenario_id"]: row for row in final_manifest(root)}
    moves, errors, issues, collisions = [], [], [], []
    destinations: set[str] = set()
    reference_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for base in (root / "data/proposals", root / "data/annotations")
        if base.exists() for path in base.rglob("*.json"))
    for path in discover_result_paths(root):
        relative = path.relative_to(root).as_posix()
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            path_identity(root, path, record)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            issues.append({"path": relative, "reason": str(exc)})
            continue
        row = manifest.get(record.get("scenario_id"))
        if row is None:
            issues.append({"path": relative, "reason": "scenario is outside final dataset"})
            continue
        completed = (A_COMPLETED_STATUSES if record.get("configuration") == "A"
                     else B_COMPLETED_STATUSES if record.get("configuration") == "B" else set())
        digest = sha256(path)
        if record.get("status") in completed:
            target = run_result_path(root, record["scenario_id"], record["run_id"],
                                     record["configuration"], manifest_row=row)
            target_relative = target.relative_to(root).as_posix()
            if target == path:
                continue
            if target.exists() or target_relative in destinations:
                collisions.append({"source": relative, "destination": target_relative})
            destinations.add(target_relative)
            moves.append({"source": relative, "destination": target_relative,
                          "sha256": digest, "run_id": record["run_id"],
                          "scenario_id": record["scenario_id"],
                          "configuration": record["configuration"],
                          "status": record["status"]})
        else:
            run_id = str(record.get("run_id") or "")
            if run_id and run_id in reference_text:
                issues.append({"path": relative,
                               "reason": "technical-error run is referenced by proposal/annotation data"})
                continue
            errors.append({"source": relative, "sha256": digest, "run_id": run_id or None,
                           "scenario_id": record.get("scenario_id"),
                           "configuration": record.get("configuration"),
                           "status": record.get("status"), "stage": record.get("error_stage"),
                           "error": record.get("error")})
    return {"schema_version": "1.0", "created_at": datetime.now(timezone.utc).isoformat(),
            "summary": {"publishable_to_move": len(moves),
                        "technical_errors_to_remove": len(errors),
                        "issues": len(issues), "collisions": len(collisions)},
            "moves": moves, "technical_errors": errors,
            "issues": issues, "collisions": collisions}


def _remove_empty(path: Path, stop: Path) -> None:
    current = path
    while current != stop and current.exists():
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def apply_plan(root: Path, plan: dict) -> dict:
    if plan["collisions"] or plan["issues"]:
        raise ValueError("migration has collisions or unresolved issues; nothing changed")
    for item in plan["moves"] + plan["technical_errors"]:
        source = root / item["source"]
        if not source.is_file() or sha256(source) != item["sha256"]:
            raise ValueError(f"source missing or changed: {item['source']}")
    for move in plan["moves"]:
        source, target = root / move["source"], root / move["destination"]
        if target.exists():
            raise ValueError(f"destination exists: {move['destination']}")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.rename(source, target)
        if sha256(target) != move["sha256"]:
            raise RuntimeError(f"hash mismatch after move: {move['destination']}")
        _remove_empty(source.parent, root / "eval/runs")
    for error in plan["technical_errors"]:
        source = root / error["source"]
        source.unlink()
        _remove_empty(source.parent, root / "eval/runs")
    result = dict(plan)
    result["applied_at"] = datetime.now(timezone.utc).isoformat()
    result["summary"] = dict(plan["summary"]) | {
        "hashes_preserved": True,
        "technical_error_summary": "eval/run_technical_errors_archive.json",
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    manifest_path = root / "eval/dataset_layout_migration_manifest.json"
    if manifest_path.exists():
        prior = json.loads(manifest_path.read_text(encoding="utf-8"))
        for move in prior.get("moves", []):
            target = root / move["destination"]
            if not target.is_file() or sha256(target) != move["sha256"]:
                raise ValueError(f"prior migration verification failed: {move['destination']}")
        current = build_plan(root)
        if not current["moves"] and not current["technical_errors"]:
            print(json.dumps(prior["summary"] | {"idempotent_rerun": True}, indent=2))
            return 0
    plan = build_plan(root)
    atomic_json(root / "eval/dataset_layout_migration_plan.json", plan)
    print(json.dumps(plan["summary"], indent=2))
    if not args.apply:
        return 1 if plan["collisions"] or plan["issues"] else 0
    applied = apply_plan(root, plan)
    atomic_json(root / "eval/run_technical_errors_archive.json",
                {"schema_version": "1.0", "errors": plan["technical_errors"]})
    atomic_json(manifest_path, applied)
    print(json.dumps(applied["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
