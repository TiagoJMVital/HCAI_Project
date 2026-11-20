"""Explicit v2 import/validation; no synthesis of legacy profile fields or labels."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from scenario_v2 import load_manifest, load_scenario

ROOT = Path(__file__).resolve().parent.parent


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def import_scenario(root: Path, source: Path, split: str) -> Path:
    if split not in {"train", "dev", "test"}:
        raise ValueError("split must be train, dev or test")
    scenario = load_scenario(source)
    rows = load_manifest(root)
    if any(row["family_id"] == scenario.family_id and row["split"] != split for row in rows):
        raise ValueError("family already assigned to the opposite split")
    target = root / "data" / "scenarios" / f"{scenario.scenario_id}.json"
    manifest = root / "data" / "benchmark_manifest.json"
    if target.exists() or any(row["scenario_id"] == scenario.scenario_id for row in rows):
        raise ValueError("scenario already imported; existing data will not be overwritten")
    # Preserve the validated contract, without changing or inventing scientific fields.
    payload = scenario.model_dump(mode="json")
    atomic_json(target, payload)
    if scenario.aggregate_requirements:
        from scenario_v2 import AggregateSidecar
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        sidecar = AggregateSidecar(schema_version="1.0", scenario_id=scenario.scenario_id,
                                   scenario_sha256_canonical=hashlib.sha256(canonical).hexdigest(),
                                   requirements=scenario.aggregate_requirements)
        atomic_json(root / "data" / "aggregate_requirements" / f"{scenario.scenario_id}.json",
                    sidecar.model_dump(mode="json"))
    if scenario.confirmed_changes:
        from scenario_v2 import ConfirmedChangesSidecar
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        sidecar = ConfirmedChangesSidecar(schema_version="1.0", scenario_id=scenario.scenario_id,
                                          scenario_sha256_canonical=hashlib.sha256(canonical).hexdigest(),
                                          changes=scenario.confirmed_changes)
        atomic_json(root / "data" / "confirmed_changes" / f"{scenario.scenario_id}.json",
                    sidecar.model_dump(mode="json"))
    rows.append({"scenario_id": scenario.scenario_id, "family_id": scenario.family_id,
                 "profile_id": scenario.profile.profile_id, "split": split})
    atomic_json(manifest, {"schema_version": "2.0", "scenarios": rows})
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate or import independent v2 scenarios")
    sub = parser.add_subparsers(dest="action", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("path", nargs="?", type=Path, help="v2 JSON; omitted validates imported benchmark")
    imported = sub.add_parser("import")
    imported.add_argument("path", type=Path)
    imported.add_argument("--split", choices=("train", "dev", "test"), required=True)
    args = parser.parse_args()
    try:
        if args.action == "import":
            print(import_scenario(ROOT, args.path, args.split))
        elif args.path:
            scenario = load_scenario(args.path)
            print(f"valid: {scenario.scenario_id} ({len(scenario.calendar.events)} events)")
        else:
            rows = load_manifest(ROOT)
            print(f"valid: {len(rows)} imported v2 scenarios")
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
