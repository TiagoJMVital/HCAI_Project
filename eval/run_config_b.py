"""Executa a configuração B em cenários sintéticos, sem alterar calendários."""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from llm import get_provider  # noqa: E402
from models import Profile  # noqa: E402
from pipeline_b import CriticSettings, run_config_b  # noqa: E402
from run_config_a import load_scenarios  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Configuração B: Proposer + Critic + regras fixas")
    parser.add_argument("--only", help="ID de um único cenário")
    parser.add_argument("--provider", choices=("iaedu", "ollama"))
    parser.add_argument("--model", help="modelo do Proposer; por omissão, configuração A")
    parser.add_argument("--critic-provider", choices=("iaedu", "ollama"),
                        help="opção futura; por omissão, igual ao Proposer")
    parser.add_argument("--critic-model", help="opção futura; por omissão, igual ao Proposer")
    parser.add_argument("--critic-threshold", type=float, default=4.0)
    parser.add_argument("--max-refinements", type=int, default=3)
    parser.add_argument("--min-dimension-score", type=int, default=1)
    parser.add_argument("--experiment-id", default=None, help="etiqueta comum para execuções A/B")
    parser.add_argument("--repeat-index", type=int, default=0, help="índice manual da repetição")
    args = parser.parse_args()
    if args.repeat_index < 0:
        parser.error("--repeat-index deve ser >= 0")
    try:
        settings = CriticSettings(threshold=args.critic_threshold,
                                  max_refinements=args.max_refinements,
                                  min_dimension_score=args.min_dimension_score)
    except ValueError as exc:
        parser.error(str(exc))

    scenarios = load_scenarios(args.only)
    if not scenarios:
        parser.error("nenhum cenário encontrado; execute python src/make_seed_scenarios.py")
    profile = Profile.model_validate_json((ROOT / "data" / "profile.json").read_text(encoding="utf-8"))
    proposer_provider = get_provider(role="PROPOSER", provider=args.provider, model=args.model)
    critic_provider = get_provider(role="CRITIC",
                                   provider=args.critic_provider or proposer_provider.name,
                                   model=args.critic_model or proposer_provider.model)
    run_id = uuid.uuid4().hex
    out_dir = ROOT / "eval" / "runs" / run_id / "B"
    out_dir.mkdir(parents=True, exist_ok=True)
    errors = 0
    for scenario in scenarios:
        started = time.monotonic()
        record = run_config_b(profile, scenario, proposer_provider=proposer_provider,
                              critic_provider=critic_provider, settings=settings)
        record.update(run_id=run_id, experiment_id=args.experiment_id,
                      repeat_index=args.repeat_index, split=scenario.split)
        record["seconds"] = round(time.monotonic() - started, 2)
        (out_dir / f"{scenario.id}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{scenario.id}: status={record['status']} decisão={record['decision']} "
              f"pontuação={record['final_score']} revisões={record['refinements']} "
              f"tempo={record['seconds']}s")
        if record["status"].endswith("_error"):
            errors += 1
    print(f"{len(scenarios)} cenário(s); {errors} erro(s); resultados em {out_dir}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
