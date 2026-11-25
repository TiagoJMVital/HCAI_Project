"""Resumable explicit executor for the documented ten-scenario A/B pilot."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from proposal_catalog_v2 import import_result  # noqa: E402
from critic import SYSTEM as CRITIC_SYSTEM  # noqa: E402
from llm import get_provider  # noqa: E402
from pipeline_b import CriticSettings  # noqa: E402
from proposer_v2 import (PROPOSER_WIRE_SCHEMA_SHA256, PROPOSER_WIRE_SCHEMA_VERSION,
                         REVISION_GUIDANCE, SYSTEM_V2)  # noqa: E402
from run_catalog_v2 import PILOT_SCENARIO_IDS, runs  # noqa: E402
from run_config_b_v2 import load_initial_proposal  # noqa: E402
from scenario_v2 import load_manifest, load_scenario  # noqa: E402

A_TERMINAL = {"proposal_ready", "invalid_proposal"}
B_TERMINAL = {"proposal_ready", "deferred_invalid_proposal", "deferred_critic_threshold"}


def latest_terminal(scenario_id: str, configuration: str) -> dict | None:
    terminal = A_TERMINAL if configuration == "A" else B_TERMINAL
    return next((row for row in runs(ROOT, scenario_id=scenario_id,
                                     configuration=configuration)
                 if row.get("status") in terminal), None)


def replayable_partial_b(scenario_id: str) -> Path | None:
    """Return a compatible B initial proposal after a Critic-stage failure.

    The normal B replay loader performs the authoritative scenario, sidecar,
    proposal and deterministic-calendar checks. Metadata checks here prevent a
    replay across experimental configurations before that loader is invoked.
    """
    manifest_row = next(row for row in load_manifest(ROOT)
                        if row["scenario_id"] == scenario_id)
    scenario = load_scenario(ROOT / "data/scenarios" / f"{scenario_id}.json")
    current_models = (get_provider(role="PROPOSER", provider="iaedu").model,
                      get_provider(role="CRITIC", provider="iaedu").model)
    current_prompts = {
        "proposer_sha256": hashlib.sha256(SYSTEM_V2.encode()).hexdigest(),
        "proposer_wire_schema_version": PROPOSER_WIRE_SCHEMA_VERSION,
        "proposer_wire_schema_sha256": PROPOSER_WIRE_SCHEMA_SHA256,
        "proposer_revision_sha256": hashlib.sha256(REVISION_GUIDANCE.encode()).hexdigest(),
        "critic_sha256": hashlib.sha256(CRITIC_SYSTEM.encode()).hexdigest(),
    }
    current_settings = CriticSettings().__dict__
    # Prefer the original compatible partial over chains of failed replays.
    for record in reversed(runs(ROOT, scenario_id=scenario_id, configuration="B")):
        if (record.get("status") != "critic_error" or record.get("error_stage") != "critic"
                or record.get("initial_proposal") is None):
            continue
        if ((record.get("proposer_provider"), record.get("critic_provider")) != ("iaedu", "iaedu")
                or (record.get("proposer_model"), record.get("critic_model")) != current_models
                or record.get("prompt_versions") != current_prompts
                or record.get("critic_settings") != current_settings):
            continue
        path = ROOT / record["_path"]
        try:
            load_initial_proposal(ROOT, path, scenario, manifest_row)
        except (ValueError, OSError, KeyError):
            continue
        return path
    return None


def execute(scenario_id: str, configuration: str,
            *, initial_proposal_from: Path | None = None) -> Path:
    script = ROOT / "eval" / f"run_config_{configuration.lower()}_v2.py"
    command = [sys.executable, str(script), "--only", scenario_id, "--provider", "iaedu"]
    if configuration == "B":
        command += ["--critic-provider", "iaedu"]
        if initial_proposal_from is not None:
            command += ["--initial-proposal-from", str(initial_proposal_from)]
    subprocess.run(command, cwd=ROOT, check=True)
    latest = runs(ROOT, scenario_id=scenario_id, configuration=configuration)[0]
    return ROOT / latest["_path"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=PILOT_SCENARIO_IDS)
    parser.add_argument("--delay", type=int,
                        default=int(os.getenv("PILOT_REQUEST_DELAY_SECONDS", "60")),
                        help="seconds between new provider runs (default: 60)")
    args = parser.parse_args()
    selected = (args.only,) if args.only else PILOT_SCENARIO_IDS
    made_call = False
    for scenario_id in selected:
        print(f"\n=== {scenario_id} ===", flush=True)
        for configuration in ("A", "B"):
            existing = latest_terminal(scenario_id, configuration)
            if existing is not None:
                path = ROOT / existing["_path"]
                print(f"{configuration}: resume existing {path} ({existing['status']})", flush=True)
            else:
                if made_call and args.delay:
                    print(f"pacing: waiting {args.delay}s before next configuration", flush=True)
                    time.sleep(args.delay)
                replay_source = replayable_partial_b(scenario_id) if configuration == "B" else None
                if replay_source is not None:
                    print(f"B recovery: replaying validated initial proposal from {replay_source}",
                          flush=True)
                path = execute(scenario_id, configuration,
                               initial_proposal_from=replay_source)
                made_call = True
                record = json.loads(path.read_text(encoding="utf-8"))
                print(f"{configuration}: new {path} ({record['status']})", flush=True)
                if record.get("rate_limit_diagnostics"):
                    classification = record["rate_limit_diagnostics"].get("classification")
                    print(f"rate limit stopped pilot: {classification}; resume later with "
                          f"{sys.executable} eval/run_pilot_v2.py --delay {args.delay}", flush=True)
                    return 2
            if configuration == "B":
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("status") in B_TERMINAL and record.get("final_proposal"):
                    try:
                        print(f"B catalog: {import_result(ROOT, path)}", flush=True)
                    except ValueError as exc:
                        print(f"B catalog skipped: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
