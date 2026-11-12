"""Avalia offline um registo A/B; não contacta fornecedores nem altera resultados."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from models import Profile, Scenario  # noqa: E402
from quality_checks import evaluate_proposal  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    args = parser.parse_args()
    record = json.loads(args.result.read_text(encoding="utf-8"))
    scenario_id = record["scenario_id"]
    scenario = Scenario.model_validate_json(
        (ROOT / "data" / "scenarios" / f"{scenario_id}.json").read_text())
    profile = Profile.model_validate_json((ROOT / "data" / "profile.json").read_text())
    checks = json.loads((ROOT / "data" / "objective_checks.json").read_text())
    proposal = record.get("final_proposal") or record.get("proposal")
    if proposal is None:
        parser.error("registo sem proposta")
    quality = evaluate_proposal(scenario, profile, proposal,
                                checks["scenarios"].get(scenario_id))
    print(json.dumps({"scenario_id": scenario_id, "configuration": record.get("configuration", "A"),
                      "quality": quality}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
