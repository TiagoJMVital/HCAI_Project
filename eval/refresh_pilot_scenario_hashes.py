#!/usr/bin/env python3
"""Refresh provenance hashes for the explicitly allowlisted repaired scenarios."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from final_dataset_v2 import dataset_root  # noqa: E402
from scenario_v2 import V2Scenario, load_scenario  # noqa: E402


ALLOWLIST = ROOT / "eval" / "pilot_scenario_allowlist.json"
STATUS = ROOT / "docs" / "scenario_final_status.csv"


def _canonical_hash(scenario: V2Scenario) -> str:
    payload = json.dumps(
        scenario.model_dump(mode="json"), sort_keys=True,
        separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="write hashes; default is a check-only preview")
    args = parser.parse_args()

    wanted = json.loads(ALLOWLIST.read_text(encoding="utf-8"))["scenario_ids"]
    with STATUS.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        rows = list(reader)
    by_id = {row["scenario_id"]: row for row in rows}
    if set(wanted) - set(by_id):
        raise ValueError(f"allowlist IDs missing from readiness table: {sorted(set(wanted) - set(by_id))}")

    data_root = dataset_root(ROOT)
    changed = False
    for scenario_id in wanted:
        row = by_id[scenario_id]
        relative = Path(row["scenario_path"])
        path = data_root / Path(*relative.parts[1:])
        scenario = V2Scenario.model_validate_json(path.read_text(encoding="utf-8"))
        canonical = _canonical_hash(scenario)
        raw = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"{scenario_id}: raw={raw} canonical={canonical}")
        if row["scenario_sha256"] != raw:
            changed = True
            row["scenario_sha256"] = raw

        for folder in ("aggregate_requirements", "confirmed_changes"):
            sidecar_path = data_root / folder / f"{scenario_id}.json"
            if not sidecar_path.exists():
                continue
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            if sidecar.get("scenario_sha256_canonical") != canonical:
                changed = True
                sidecar["scenario_sha256_canonical"] = canonical
                if args.write:
                    sidecar_path.write_text(
                        json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )

        if args.write:
            load_scenario(path)

    if args.write and changed:
        with STATUS.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    print("updated" if args.write and changed else "no writes" if not args.write else "already current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
