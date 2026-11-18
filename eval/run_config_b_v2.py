"""Explicit single-scenario B run for v2 inputs; never invoked by opening the UI."""
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
from critic import SYSTEM as CRITIC_SYSTEM  # noqa: E402
from llm import get_provider  # noqa: E402
from models import Proposal  # noqa: E402
from pipeline_b import CriticSettings, run_config_b  # noqa: E402
from proposer_v2 import SYSTEM_V2, V2RuntimeScenario, propose_v2  # noqa: E402
from scenario_v2 import load_manifest, load_scenario  # noqa: E402


def run_one(root: Path, scenario_id: str, proposer_provider, critic_provider,
            settings: CriticSettings | None = None, *, experiment_id: str | None = None,
            repeat_index: int = 0) -> Path:
    rows = load_manifest(root)
    row = next((r for r in rows if r["scenario_id"] == scenario_id), None)
    if row is None:
        raise ValueError("v2 scenario not imported")
    source = load_scenario(root / "data" / "scenarios" / f"{scenario_id}.json")
    runtime = V2RuntimeScenario(source)
    started = time.monotonic()
    record = run_config_b(source.profile, runtime, proposer_provider=proposer_provider,
                          critic_provider=critic_provider, settings=settings,
                          proposer_fn=propose_v2,
                          validator_fn=lambda _calendar, proposal, _profile:
                          simulate(source, proposal)[1]["violations"])
    record.update(schema_version="2.0", profile_id=source.profile.profile_id,
                  split=row["split"], run_id=uuid.uuid4().hex,
                  experiment_id=experiment_id, repeat_index=repeat_index,
                  generated_at=datetime.now(timezone.utc).isoformat(),
                  prompt_versions={"proposer_sha256": hashlib.sha256(SYSTEM_V2.encode()).hexdigest(),
                                   "critic_sha256": hashlib.sha256(CRITIC_SYSTEM.encode()).hexdigest()},
                  seconds=round(time.monotonic() - started, 3))
    if record["final_proposal"] is not None:
        _, report = simulate(source, Proposal.model_validate(record["final_proposal"]))
        record["technical_validation"] = report
    out = root / "eval" / "runs" / record["run_id"] / "B" / f"{scenario_id}.json"
    atomic_json(out, record)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Explicit B generation for one imported v2 scenario")
    parser.add_argument("--only", required=True, help="exactly one scenario ID")
    parser.add_argument("--provider", choices=("iaedu", "ollama"))
    parser.add_argument("--model")
    parser.add_argument("--critic-provider", choices=("iaedu", "ollama"))
    parser.add_argument("--critic-model")
    parser.add_argument("--critic-threshold", type=float, default=4.0)
    parser.add_argument("--max-refinements", type=int, default=3)
    parser.add_argument("--experiment-id")
    parser.add_argument("--repeat-index", type=int, default=0)
    args = parser.parse_args()
    if args.repeat_index < 0:
        parser.error("--repeat-index must be >= 0")
    proposer = get_provider(role="PROPOSER", provider=args.provider, model=args.model)
    critic = get_provider(role="CRITIC", provider=args.critic_provider or proposer.name,
                          model=args.critic_model or proposer.model)
    path = run_one(ROOT, args.only, proposer, critic,
                   CriticSettings(threshold=args.critic_threshold,
                                  max_refinements=args.max_refinements),
                   experiment_id=args.experiment_id, repeat_index=args.repeat_index)
    record = json.loads(path.read_text(encoding="utf-8"))
    print(f"{path}: {record['status']}; import separately with src/proposal_catalog_v2.py")


if __name__ == "__main__":
    main()
