"""Safely migrate eval/runs from run-first to scenario-first storage.

Dry-run is the default. Reports are written outside the run tree so they can be
used to verify the migration without becoming run artifacts themselves.
"""
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
from run_paths_v2 import CONFIGURATIONS, path_identity  # noqa: E402

REPORT_VERSION = "1.0"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def inventory(root: Path) -> list[dict]:
    runs_root = root / "eval" / "runs"
    if not runs_root.exists():
        return []
    return [{"path": _relative(path, root), "size": path.stat().st_size,
             "sha256": sha256(path)}
            for path in sorted(runs_root.rglob("*")) if path.is_file()]


def build_plan(root: Path) -> dict:
    runs_root = root / "eval" / "runs"
    original = inventory(root)
    hashes = {item["path"]: item["sha256"] for item in original}
    issues: list[dict] = []
    legacy: dict[str, list[Path]] = {}
    valid_results: dict[Path, tuple[str, str, str]] = {}
    already_scenario_first = 0

    for path in sorted(runs_root.rglob("*.json")) if runs_root.exists() else []:
        relative = path.relative_to(runs_root)
        if path.parent.name not in CONFIGURATIONS or len(relative.parts) not in (3, 4):
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            identity = path_identity(root, path, record)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            issues.append({"path": _relative(path, root), "reason": str(exc)})
            continue
        valid_results[path] = identity
        if len(relative.parts) == 4:
            already_scenario_first += 1
        else:
            legacy.setdefault(relative.parts[0], []).append(path)

    moves: list[dict] = []
    mapped_sources: set[Path] = set()
    for run_id, results in sorted(legacy.items()):
        run_dir = runs_root / run_id
        all_files = sorted(path for path in run_dir.rglob("*") if path.is_file())
        identities = {path: valid_results[path] for path in results}
        scenario_ids = {identity[0] for identity in identities.values()}
        by_configuration: dict[str, set[str]] = {}
        for path, (scenario_id, _, _) in identities.items():
            by_configuration.setdefault(path.relative_to(run_dir).parts[0], set()).add(scenario_id)

        for source in all_files:
            relative_in_run = source.relative_to(run_dir)
            scenario_id: str | None = None
            if source in identities:
                scenario_id = identities[source][0]
            elif len(scenario_ids) == 1:
                scenario_id = next(iter(scenario_ids))
            elif relative_in_run.parts:
                candidates = by_configuration.get(relative_in_run.parts[0], set())
                if len(candidates) == 1:
                    scenario_id = next(iter(candidates))
            if scenario_id is None:
                issues.append({"path": _relative(source, root),
                               "reason": "auxiliary artifact cannot be associated with one scenario safely"})
                continue
            destination = runs_root / scenario_id / run_id / relative_in_run
            moves.append({"source": _relative(source, root),
                          "destination": _relative(destination, root),
                          "sha256": hashes[_relative(source, root)],
                          "size": source.stat().st_size,
                          "scenario_id": scenario_id, "run_id": run_id})
            mapped_sources.add(source)

    collisions: list[dict] = []
    destinations: dict[str, str] = {}
    for move in moves:
        source = root / move["source"]
        destination = root / move["destination"]
        previous = destinations.get(move["destination"])
        if previous is not None and previous != move["source"]:
            collisions.append({"destination": move["destination"],
                               "sources": [previous, move["source"]]})
        destinations[move["destination"]] = move["source"]
        if destination.exists() and destination != source:
            collisions.append({"source": move["source"],
                               "destination": move["destination"],
                               "reason": "destination already exists",
                               "destination_sha256": sha256(destination) if destination.is_file() else None})

    legacy_files = {path for run_id in legacy for path in (runs_root / run_id).rglob("*")
                    if path.is_file()}
    for path in sorted(legacy_files - mapped_sources):
        if not any(issue["path"] == _relative(path, root) for issue in issues):
            issues.append({"path": _relative(path, root),
                           "reason": "legacy artifact was not mapped"})

    return {
        "schema_version": REPORT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runs_root": _relative(runs_root, root),
        "inventory": original,
        "summary": {"inventory_files": len(original),
                    "legacy_run_directories": len(legacy),
                    "scenarios_to_migrate": len({move["scenario_id"] for move in moves}),
                    "artifacts_to_migrate": len(moves),
                    "already_scenario_first_results": already_scenario_first,
                    "issues": len(issues), "collisions": len(collisions)},
        "moves": moves, "issues": issues, "collisions": collisions,
    }


def _remove_empty_legacy_directories(root: Path, run_ids: set[str]) -> None:
    runs_root = root / "eval" / "runs"
    for run_id in sorted(run_ids):
        run_dir = runs_root / run_id
        if not run_dir.exists():
            continue
        for directory in sorted((path for path in run_dir.rglob("*") if path.is_dir()),
                                key=lambda path: len(path.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        try:
            run_dir.rmdir()
        except OSError:
            pass


def apply_plan(root: Path, plan: dict) -> dict:
    if plan["collisions"]:
        raise ValueError("migration has destination collisions; nothing was moved")
    completed = []
    for move in plan["moves"]:
        source = root / move["source"]
        destination = root / move["destination"]
        if not source.is_file():
            raise ValueError(f"source disappeared before migration: {move['source']}")
        if destination.exists():
            raise ValueError(f"destination appeared before migration: {move['destination']}")
        if sha256(source) != move["sha256"]:
            raise ValueError(f"source changed after inventory: {move['source']}")
    for move in plan["moves"]:
        source = root / move["source"]
        destination = root / move["destination"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.rename(source, destination)
        if sha256(destination) != move["sha256"]:
            raise RuntimeError(f"post-migration hash mismatch: {move['destination']}")
        completed.append(move)
    _remove_empty_legacy_directories(root, {move["run_id"] for move in completed})
    current = inventory(root)
    expected_paths = ({item["path"] for item in plan["inventory"]} -
                      {move["source"] for move in completed}) | \
                     {move["destination"] for move in completed}
    current_paths = {item["path"] for item in current}
    if current_paths != expected_paths:
        raise RuntimeError("post-migration inventory paths do not account for every original artifact")
    if len(current) != len(plan["inventory"]):
        raise RuntimeError("post-migration artifact count changed")
    current_hashes = {item["path"]: item["sha256"] for item in current}
    for move in completed:
        if current_hashes.get(move["destination"]) != move["sha256"]:
            raise RuntimeError(f"post-migration verification failed: {move['destination']}")
    return {
        "schema_version": REPORT_VERSION,
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "summary": {"run_directories_migrated": len({move["run_id"] for move in completed}),
                    "scenarios": len({move["scenario_id"] for move in completed}),
                    "artifacts_migrated": len(completed),
                    "ambiguous_artifacts_left_unchanged": len(plan["issues"]),
                    "hashes_preserved": True,
                    "original_artifact_count": len(plan["inventory"]),
                    "final_artifact_count": len(current)},
        "moves": completed, "issues": plan["issues"], "collisions": [],
    }


def verify_manifest(root: Path, manifest: dict) -> None:
    for move in manifest.get("moves", []):
        destination = root / move["destination"]
        if not destination.is_file() or sha256(destination) != move["sha256"]:
            raise ValueError(f"manifest verification failed: {move['destination']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="apply the preflighted migration")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    plan = build_plan(root)
    inventory_path = root / "eval" / "run_migration_inventory.json"
    plan_path = root / "eval" / "run_migration_plan.json"
    manifest_path = root / "eval" / "run_migration_manifest.json"
    existing_manifest = None
    if manifest_path.exists():
        existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        verify_manifest(root, existing_manifest)
    # Once an apply succeeds, retain its original pre-migration inventory.
    if existing_manifest is None:
        atomic_json(inventory_path,
                    {"schema_version": REPORT_VERSION, "created_at": plan["created_at"],
                     "artifacts": plan["inventory"]})
        atomic_json(plan_path, {key: value for key, value in plan.items() if key != "inventory"})
    elif existing_manifest.get("moves"):
        # Preserve (or reconstruct for older script versions) the actionable
        # dry-run plan instead of replacing it with an empty idempotency check.
        saved_plan = (json.loads(plan_path.read_text(encoding="utf-8"))
                      if plan_path.exists() else {})
        if not saved_plan.get("moves"):
            original_inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            summary = existing_manifest["summary"]
            atomic_json(plan_path, {
                "schema_version": REPORT_VERSION,
                "created_at": original_inventory["created_at"],
                "runs_root": "eval/runs",
                "summary": {"inventory_files": summary["original_artifact_count"],
                            "legacy_run_directories": summary["run_directories_migrated"],
                            "scenarios_to_migrate": summary["scenarios"],
                            "artifacts_to_migrate": summary["artifacts_migrated"],
                            "already_scenario_first_results": 0,
                            "issues": len(existing_manifest.get("issues", [])),
                            "collisions": 0},
                "moves": existing_manifest["moves"],
                "issues": existing_manifest.get("issues", []), "collisions": [],
            })
    print(json.dumps(plan["summary"], indent=2))
    if not args.apply:
        return 1 if plan["collisions"] else 0
    if existing_manifest is not None and not plan["moves"]:
        print(json.dumps(existing_manifest["summary"] | {"idempotent_rerun": True}, indent=2))
        return 0
    manifest = apply_plan(root, plan)
    verify_manifest(root, manifest)
    if existing_manifest is not None:
        manifest["moves"] = existing_manifest.get("moves", []) + manifest["moves"]
        manifest["issues"] = existing_manifest.get("issues", []) + manifest["issues"]
    atomic_json(manifest_path, manifest)
    print(json.dumps(manifest["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
