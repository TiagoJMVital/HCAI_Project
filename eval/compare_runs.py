"""Agrupa registos A/B por experimento, cenário e repetição, sem usar rótulos."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from run_paths_v2 import discover_result_paths  # noqa: E402


def collect(runs_root: Path, experiment_id: str) -> list[dict]:
    grouped: dict[tuple[str, int], dict] = defaultdict(dict)
    root = runs_root.parent.parent
    seen: set[tuple[str, str, str]] = set()
    for path in discover_result_paths(root):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("schema_version") != "2.0" or record.get("configuration") not in ("A", "B"):
            continue
        if record.get("experiment_id") != experiment_id:
            continue
        config = record.get("configuration", path.parent.name)
        identity = (record["scenario_id"], record["run_id"], config)
        if identity in seen:
            continue
        seen.add(identity)
        key = (record["scenario_id"], record.get("repeat_index", 0))
        if config in grouped[key]:
            raise ValueError(f"registos duplicados para {key} em {config}")
        grouped[key][config] = {
            "run_id": record.get("run_id"), "family": record.get("family"),
            "split": record.get("split"), "provider": record.get("provider") or record.get("proposer_provider"),
            "model": record.get("model") or record.get("proposer_model"),
            "status": record.get("status"), "decision": record.get("decision"),
            "seconds": record.get("seconds"),
            "proposal": record.get("proposal") or record.get("final_proposal"),
            "critic_score": record.get("final_score"),
        }
    rows = []
    for (scenario_id, repeat_index), configs in sorted(grouped.items()):
        a, b = configs.get("A"), configs.get("B")
        rows.append({"scenario_id": scenario_id, "repeat_index": repeat_index,
                     "A": a, "B": b,
                     "paired": bool(a and b),
                     "same_proposer_model": bool(a and b and a["provider"] == b["provider"]
                                                  and a["model"] == b["model"])})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-id", required=True)
    args = parser.parse_args()
    print(json.dumps({"experiment_id": args.experiment_id,
                      "rows": collect(ROOT / "eval" / "runs", args.experiment_id)},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
