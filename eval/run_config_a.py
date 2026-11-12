"""Configuração A: Proposer + regras fixas; grava cada execução separadamente."""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from calendar_ops import find_violations  # noqa: E402
from llm import LLMError, get_provider  # noqa: E402
from models import Profile, Scenario  # noqa: E402
from proposer import propose  # noqa: E402
from rules import rule_based_decision  # noqa: E402


def load_scenarios(only: str | None) -> list[Scenario]:
    out = []
    for p in sorted((ROOT / "data" / "scenarios").glob("*.json")):
        s = Scenario.model_validate(json.loads(p.read_text(encoding="utf-8")))
        if only is None or s.id == only:
            out.append(s)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    ap.add_argument("--provider", choices=("iaedu", "ollama"), default=None)
    ap.add_argument("--only", default=None, help="id de um cenário")
    ap.add_argument("--experiment-id", default=None, help="etiqueta comum para execuções A/B")
    ap.add_argument("--repeat-index", type=int, default=0, help="índice manual da repetição")
    args = ap.parse_args()
    if args.repeat_index < 0:
        ap.error("--repeat-index deve ser >= 0")

    profile = Profile.model_validate_json((ROOT / "data" / "profile.json").read_text(encoding="utf-8"))
    scenarios = load_scenarios(args.only)
    if not scenarios:
        ap.error("nenhum cenário encontrado; execute python src/make_seed_scenarios.py")
    client = get_provider(role="PROPOSER", provider=args.provider, model=args.model)
    run_id = uuid.uuid4().hex
    out_dir = ROOT / "eval" / "runs" / run_id / "A"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for s in scenarios:
        t0 = time.time()
        rec = {"configuration": "A", "run_id": run_id,
               "experiment_id": args.experiment_id, "repeat_index": args.repeat_index,
               "scenario_id": s.id, "family": s.family, "split": s.split, "category": s.category,
               "provider": client.name, "model": client.model,
               "generation_config": client.generation_config()}
        try:
            prop = propose(profile, s, provider=client)
            violations = find_violations(s.calendar, prop, profile)
            decision, reasons = rule_based_decision(prop, s.calendar, violations)
            rec.update(proposal=prop.model_dump(), violations=violations,
                       decision=decision, reasons=reasons,
                       status="invalid_proposal" if violations else "proposal_ready")
        except LLMError as e:
            rec.update(error=str(e), violations=None, decision=None, reasons=[],
                       status="llm_error")
        rec["seconds"] = round(time.time() - t0, 1)
        (out_dir / f"{s.id}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
        ref = s.reference_decision or f"({s.draft_label}?)"
        rows.append((s.id, s.category, rec["decision"] or "ERRO", ref,
                     len(rec["violations"] or []), rec["seconds"]))
        print(f"{s.id:<16} {s.category:<10} decisão={rows[-1][2]:<6} ref={ref:<9} viol={rows[-1][4]} {rec['seconds']}s")

    n_viol = sum(1 for r in rows if r[4] > 0)
    print(f"\n{len(rows)} cenários | {n_viol} com violações de restrições | resultados em {out_dir}")
    print("Nota: ref entre parênteses = pré-rótulo, NÃO anotação humana.")


if __name__ == "__main__":
    main()
