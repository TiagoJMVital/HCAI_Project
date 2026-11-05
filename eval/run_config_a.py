"""Configuração A: Proposer + regras fixas de autonomia.

Uso (a partir da raiz do projeto, com o Ollama a correr):
    python eval/run_config_a.py                  # todos os cenários
    python eval/run_config_a.py --only soft_gym_01
    python eval/run_config_a.py --model gemma2:2b
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from calendar_ops import find_violations  # noqa: E402
from llm import DEFAULT_MODEL, LLMError  # noqa: E402
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
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--only", default=None, help="id de um cenário")
    args = ap.parse_args()

    profile = Profile.model_validate_json((ROOT / "data" / "profile.json").read_text(encoding="utf-8"))
    out_dir = ROOT / "eval" / "results" / "A"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for s in load_scenarios(args.only):
        t0 = time.time()
        rec = {"scenario_id": s.id, "category": s.category, "model": args.model}
        try:
            prop = propose(profile, s, model=args.model)
            violations = find_violations(s.calendar, prop, profile)
            decision, reasons = rule_based_decision(prop, s.calendar, violations)
            rec.update(proposal=prop.model_dump(), violations=violations,
                       decision=decision, reasons=reasons)
        except LLMError as e:
            rec.update(error=str(e), violations=[], decision=None, reasons=[])
        rec["seconds"] = round(time.time() - t0, 1)
        (out_dir / f"{s.id}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
        ref = s.reference_decision or f"({s.draft_label}?)"
        rows.append((s.id, s.category, rec["decision"] or "ERRO", ref, len(rec["violations"]), rec["seconds"]))
        print(f"{s.id:<16} {s.category:<10} decisão={rows[-1][2]:<6} ref={ref:<9} viol={rows[-1][4]} {rec['seconds']}s")

    n_viol = sum(1 for r in rows if r[4] > 0)
    print(f"\n{len(rows)} cenários | {n_viol} com violações de restrições | resultados em {out_dir}")
    print("Nota: ref entre parênteses = pré-rótulo, NÃO anotação humana.")


if __name__ == "__main__":
    main()
