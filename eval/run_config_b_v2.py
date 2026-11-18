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
from critic import SYSTEM as CRITIC_SYSTEM, final_calendar_view  # noqa: E402
from llm import get_provider  # noqa: E402
from models import Proposal  # noqa: E402
from pipeline_b import CriticSettings, run_config_b  # noqa: E402
from proposer_v2 import REVISION_GUIDANCE, SYSTEM_V2, V2RuntimeScenario, propose_v2  # noqa: E402
from scenario_v2 import V2Scenario, load_manifest, load_scenario  # noqa: E402


def load_initial_proposal(root: Path, source_path: Path, scenario: V2Scenario,
                          manifest_row: dict) -> tuple[Proposal, dict]:
    """Load a B run's first proposal and verify its scenario provenance.

    This is read-only. Any recorded first-iteration calendar is recomputed with
    the current simulator, so a changed scenario cannot silently be replayed.
    """
    raw_bytes = source_path.read_bytes()
    source_run = json.loads(raw_bytes)
    if (source_run.get("schema_version"), source_run.get("configuration")) != ("2.0", "B"):
        raise ValueError("initial proposal source must be a schema 2.0 B run")
    expected = {"scenario_id": scenario.scenario_id,
                "family": scenario.family_id,
                "profile_id": scenario.profile.profile_id,
                "split": manifest_row["split"]}
    if any(source_run.get(key) != value for key, value in expected.items()):
        raise ValueError("initial proposal source does not match scenario, family, profile or split")
    if not source_run.get("run_id"):
        raise ValueError("initial proposal source has no run ID")
    iterations = source_run.get("iterations")
    raw_proposal = source_run.get("initial_proposal")
    if (not isinstance(iterations, list) or not iterations or
            raw_proposal is None or raw_proposal != iterations[0].get("proposal")):
        raise ValueError("initial proposal is missing or differs from the first iteration")
    proposal = Proposal.model_validate(raw_proposal)
    if proposal.model_dump(mode="json") != raw_proposal:
        raise ValueError("initial proposal cannot be replayed byte-for-byte as structured fields")
    simulated, validation = simulate(scenario, proposal)
    if simulated is None or not validation["valid"]:
        raise ValueError("initial proposal fails current deterministic validation")
    first = iterations[0]
    calendar_verified = first.get("result_calendar") is not None
    if calendar_verified:
        expected_calendar = final_calendar_view(
            simulated, proposal, original_ids={event.id for event in scenario.calendar.events},
            timezone=scenario.profile.timezone)
        if first["result_calendar"] != expected_calendar or first.get("validation") != validation:
            raise ValueError("source first-iteration calendar/validation differs from current simulation")
    try:
        label = str(source_path.resolve().relative_to(root.resolve()))
    except ValueError:
        label = str(source_path.resolve())
    canonical = json.dumps(proposal.model_dump(mode="json"), sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    provenance = {
        "source_path": label,
        "source_run_id": source_run["run_id"],
        "source_run_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "source_prompt_versions": source_run.get("prompt_versions"),
        "source_critic_policy_version": source_run.get("critic_policy_version"),
        "initial_proposal_sha256_canonical": hashlib.sha256(canonical).hexdigest(),
        "current_scenario_sha256": hashlib.sha256(
            (root / "data" / "scenarios" / f"{scenario.scenario_id}.json").read_bytes()).hexdigest(),
        "source_calendar_verified_against_current_simulator": calendar_verified,
    }
    return proposal, provenance


def run_one(root: Path, scenario_id: str, proposer_provider, critic_provider,
            settings: CriticSettings | None = None, *, experiment_id: str | None = None,
            repeat_index: int = 0,
            initial_proposal_from: Path | None = None) -> Path:
    rows = load_manifest(root)
    row = next((r for r in rows if r["scenario_id"] == scenario_id), None)
    if row is None:
        raise ValueError("v2 scenario not imported")
    source = load_scenario(root / "data" / "scenarios" / f"{scenario_id}.json")
    replay_proposal, replay_source = (load_initial_proposal(root, initial_proposal_from, source, row)
                                     if initial_proposal_from is not None else (None, None))
    runtime = V2RuntimeScenario(source)
    started = time.monotonic()
    record = run_config_b(source.profile, runtime, proposer_provider=proposer_provider,
                          critic_provider=critic_provider, settings=settings,
                          proposer_fn=propose_v2,
                          simulate_fn=lambda proposal: simulate(source, proposal),
                          initial_proposal=replay_proposal)
    if replay_source is not None:
        record["replay_source"] = replay_source
    record.update(schema_version="2.0", profile_id=source.profile.profile_id,
                  split=row["split"], run_id=uuid.uuid4().hex,
                  experiment_id=experiment_id, repeat_index=repeat_index,
                  generated_at=datetime.now(timezone.utc).isoformat(),
                  prompt_versions={"proposer_sha256": hashlib.sha256(SYSTEM_V2.encode()).hexdigest(),
                                   "proposer_revision_sha256": hashlib.sha256(REVISION_GUIDANCE.encode()).hexdigest(),
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
    parser.add_argument("--initial-proposal-from", type=Path,
                        help="reuse the first proposal from a prior schema-2 B run; skip initial Proposer call")
    args = parser.parse_args()
    if args.repeat_index < 0:
        parser.error("--repeat-index must be >= 0")
    proposer = get_provider(role="PROPOSER", provider=args.provider, model=args.model)
    critic = get_provider(role="CRITIC", provider=args.critic_provider or proposer.name,
                          model=args.critic_model or proposer.model)
    path = run_one(ROOT, args.only, proposer, critic,
                   CriticSettings(threshold=args.critic_threshold,
                                  max_refinements=args.max_refinements),
                   experiment_id=args.experiment_id, repeat_index=args.repeat_index,
                   initial_proposal_from=args.initial_proposal_from)
    record = json.loads(path.read_text(encoding="utf-8"))
    print(f"{path}: {record['status']}; import separately with src/proposal_catalog_v2.py")


if __name__ == "__main__":
    main()
