"""Valida profile.json e todos os cenários; verifica separação treino/teste.

Uso:  python src/validate_data.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from models import Profile, Scenario

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    errors = 0
    try:
        Profile.model_validate_json((ROOT / "data" / "profile.json").read_text(encoding="utf-8"))
        print("profile.json OK")
    except Exception as e:  # noqa: BLE001
        print("profile.json INVÁLIDO:", e)
        errors += 1

    family_splits: dict[str, set[str]] = defaultdict(set)
    n = 0
    for p in sorted((ROOT / "data" / "scenarios").glob("*.json")):
        try:
            s = Scenario.model_validate(json.loads(p.read_text(encoding="utf-8")))
            family_splits[s.family].add(s.split)
            n += 1
        except Exception as e:  # noqa: BLE001
            print(f"{p.name} INVÁLIDO: {e}")
            errors += 1
    print(f"{n} cenários válidos")

    for fam, splits in family_splits.items():
        if len(splits) > 1:
            print(f"ERRO: família '{fam}' aparece em treino E teste (fuga de dados)")
            errors += 1
    if errors == 0:
        print("Separação treino/teste por família OK")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
