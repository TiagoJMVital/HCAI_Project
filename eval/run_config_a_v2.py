"""Explicit single-scenario v2 A baseline using the same v2 Proposer as B."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from benchmark_v2 import atomic_json  # noqa: E402
from calendar_v2 import simulate  # noqa: E402
from llm import LLMError, get_provider  # noqa: E402
from proposer_v2 import SYSTEM_V2, V2RuntimeScenario, propose_v2  # noqa: E402
from rules import rule_based_decision  # noqa: E402
from scenario_v2 import confirmed_changes_fingerprint, load_manifest, load_scenario  # noqa: E402


def run_one(root: Path, scenario_id: str, provider, *, experiment_id: str | None = None,
            repeat_index: int = 0) -> Path:
    row = next((r for r in load_manifest(root) if r["scenario_id"] == scenario_id), None)
    if row is None:
        raise ValueError("v2 scenario not imported")
    scenario = load_scenario(root / "data" / "scenarios" / f"{scenario_id}.json")
    aggregate_fingerprint = (hashlib.sha256(json.dumps(
        [rule.model_dump(mode="json") for rule in scenario.aggregate_requirements],
        sort_keys=True).encode()).hexdigest() if scenario.aggregate_requirements else None)
    run_id = uuid.uuid4().hex
    started = time.monotonic()
    record = {"schema_version": "2.0", "configuration": "A", "run_id": run_id,
              "experiment_id": experiment_id, "repeat_index": repeat_index,
              "scenario_id": scenario_id, "family": scenario.family_id,
              "profile_id": scenario.profile.profile_id, "split": row["split"],
              "aggregate_requirements_sha256": aggregate_fingerprint,
              "confirmed_changes_sha256": confirmed_changes_fingerprint(scenario),
              "provider": provider.name, "model": provider.model,
              "generation_config": provider.generation_config(),
              "prompt_versions": {"proposer_sha256": hashlib.sha256(SYSTEM_V2.encode()).hexdigest()},
              "generated_at": datetime.now(timezone.utc).isoformat(),
              "proposal": None, "technical_validation": None, "decision": None,
              "reasons": [], "status": "running"}
    try:
        proposal = propose_v2(scenario.profile, V2RuntimeScenario(scenario), provider=provider)
        _, validation = simulate(scenario, proposal)
        decision, reasons = rule_based_decision(proposal, scenario.calendar.events,
                                                validation["violations"])
        record.update(proposal=proposal.model_dump(), technical_validation=validation,
                      decision=decision, reasons=reasons,
                      status="proposal_ready" if validation["valid"] else "invalid_proposal")
    except LLMError as exc:
        record.update(status="llm_error", error=str(exc), safe_action="no_autonomous_action")
    except Exception:
        record.update(status="validation_error", error="technical validation failed",
                      safe_action="no_autonomous_action")
    record["seconds"] = round(time.monotonic() - started, 3)
    target = root / "eval" / "runs" / run_id / "A" / f"{scenario_id}.json"
    atomic_json(target, record)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Explicit A baseline for one imported v2 scenario")
    parser.add_argument("--only", required=True)
    parser.add_argument("--provider", choices=("iaedu", "ollama"))
    parser.add_argument("--model")
    parser.add_argument("--experiment-id")
    parser.add_argument("--repeat-index", type=int, default=0)
    args = parser.parse_args()
    if args.repeat_index < 0:
        parser.error("--repeat-index must be >= 0")
    path = run_one(ROOT, args.only, get_provider(role="PROPOSER", provider=args.provider, model=args.model),
                   experiment_id=args.experiment_id, repeat_index=args.repeat_index)
    print(f"{path}: {json.loads(path.read_text())['status']}")


if __name__ == "__main__":
    main()
