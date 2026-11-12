"""Manifesto, isolamento por família e folds agrupados apenas no treino."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from models import Scenario


def validate_benchmark(root: Path) -> tuple[list[str], list[dict]]:
    errors: list[str] = []
    manifest_path = root / "data" / "benchmark_manifest.json"
    if not manifest_path.exists():
        return ["benchmark_manifest.json inexistente"], []
    try:
        rows = json.loads(manifest_path.read_text(encoding="utf-8"))["scenarios"]
    except (OSError, ValueError, KeyError, TypeError):
        return ["manifesto inválido"], []
    if not isinstance(rows, list) or not rows:
        return ["manifesto vazio ou inválido"], []

    ids: set[str] = set()
    family_splits: dict[str, set[str]] = defaultdict(set)
    base_splits: dict[str, set[str]] = defaultdict(set)
    base_families: dict[str, set[str]] = defaultdict(set)
    base_factors: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        try:
            sid, base, family, split = (row[k] for k in
                                        ("scenario_id", "base_id", "family", "split"))
            if not all(isinstance(v, str) and v for v in (sid, base, family, split)):
                raise ValueError("identificador vazio")
            if sid in ids:
                errors.append(f"ID duplicado no manifesto: {sid}")
            ids.add(sid)
            family_splits[family].add(split)
            base_splits[base].add(split)
            base_families[base].add(family)
            base_factors[base].add(json.dumps(row["factors"], sort_keys=True))
            path = root / "data" / "scenarios" / f"{sid}.json"
            if not path.is_file():
                errors.append(f"cenário em falta: {sid}")
                continue
            scenario = Scenario.model_validate_json(path.read_text(encoding="utf-8"))
            if (scenario.id, scenario.family, scenario.split, scenario.category) != (
                sid, family, split, row["category"]
            ):
                errors.append(f"metadados divergentes: {sid}")
            if scenario.reference_decision is not None or scenario.annotations:
                errors.append(f"anotação humana no cenário-base: {sid}; usar ficheiros separados")
            event_ids = [event.id for event in scenario.calendar]
            if len(event_ids) != len(set(event_ids)):
                errors.append(f"event_id duplicado no calendário: {sid}")
        except (KeyError, TypeError, ValueError, OSError) as exc:
            errors.append(f"entrada inválida no manifesto: {type(exc).__name__}")
    files = {path.stem for path in (root / "data" / "scenarios").glob("*.json")}
    for sid in sorted(files - ids):
        errors.append(f"cenário sem manifesto: {sid}")
    for family, splits in family_splits.items():
        if len(splits) != 1 or not splits <= {"train", "test"}:
            errors.append(f"família em treino e teste ou split inválido: {family}")
    for base, splits in base_splits.items():
        if len(splits) != 1 or len(base_families[base]) != 1:
            errors.append(f"base dividida entre famílias/splits: {base}")
        if len(base_factors[base]) < 2:
            errors.append(f"base sem variação de fatores documentada: {base}")
    if not any(row.get("split") == "train" for row in rows):
        errors.append("sem cenários de treino")
    if not any(row.get("split") == "test" for row in rows):
        errors.append("sem cenários de teste")
    return errors, rows


def grouped_train_folds(rows: list[dict], n_splits: int = 3) -> list[dict]:
    """Folds por família, sem incluir nenhuma família do teste final."""
    train = [row for row in rows if row["split"] == "train"]
    families = sorted({row["family"] for row in train})
    if not 2 <= n_splits <= len(families):
        raise ValueError("n_splits exige pelo menos 2 e no máximo o número de famílias de treino")
    buckets = [set() for _ in range(n_splits)]
    for index, family in enumerate(families):
        buckets[index % n_splits].add(family)
    folds = []
    for index, validation_families in enumerate(buckets):
        folds.append({
            "fold": index,
            "validation_families": sorted(validation_families),
            "train_ids": sorted(row["scenario_id"] for row in train
                                if row["family"] not in validation_families),
            "validation_ids": sorted(row["scenario_id"] for row in train
                                     if row["family"] in validation_families),
        })
    return folds
