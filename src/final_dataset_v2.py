"""Validated access to the immutable final 100-scenario dataset."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

from scenario_v2 import load_scenario

EXPECTED_ARCHIVE_SHA256 = "8f0381ecda376923be74a16f654d7a4973d604cf9aba838269fb52bdd92cac47"
EXPECTED_SPLITS = {"train": 60, "dev": 10, "test": 30}
FAMILY_FOLDERS = {
    "elite_athlete_student_schedule_conflict": "atletaAltaCompeticao",
    "content_creator_schedule_conflict": "criadorDeConteudo",
    "nurse_shift_worker_masters_schedule_conflict": "enfermeira",
    "freelancer_schedule_conflict": "freelancer",
    "parent_young_children_schedule_conflict": "paiMae",
    "working_student_schedule_conflict": "trabalhadorEstudante",
    "high_school_student_schedule_conflict": "secundario",
    "international_project_manager_schedule_conflict": "gestorProjetos",
    "cleaning_lady_schedule_conflict": "profissionalLimpeza",
    "university_professor_schedule_conflict": "docenteUniversitario",
}
EXPECTED_FAMILIES = {
    "train": {
        "elite_athlete_student_schedule_conflict",
        "content_creator_schedule_conflict",
        "nurse_shift_worker_masters_schedule_conflict",
        "freelancer_schedule_conflict",
        "parent_young_children_schedule_conflict",
        "working_student_schedule_conflict",
    },
    "dev": {"high_school_student_schedule_conflict"},
    "test": {
        "international_project_manager_schedule_conflict",
        "cleaning_lady_schedule_conflict",
        "university_professor_schedule_conflict",
    },
}
ELIGIBLE_STATES = {
    "ready_for_pilot",
    "ready_with_uncertainty",
    "ready_with_legitimate_uncertainty",
    "intentional_no_op",
}
BLOCKED_STATE = "blocked_real_issue"


def dataset_root(root: Path) -> Path:
    """Return the repository-owned dataset, with read-only legacy fallback."""
    root = root.resolve()
    local = root / "scenarios"
    if local.is_dir():
        return local
    return root.parent / "scenarios"


def manifest_path(root: Path) -> Path:
    return dataset_root(root) / "benchmark_manifest.json"


def manifest_sha256(root: Path) -> str:
    return hashlib.sha256(manifest_path(root).read_bytes()).hexdigest()


def _status_rows(root: Path) -> dict[str, dict]:
    path = root / "docs" / "scenario_final_status.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 100 or len({row["scenario_id"] for row in rows}) != 100:
        raise ValueError("final readiness table must contain 100 unique scenarios")
    return {row["scenario_id"]: row for row in rows}


def _dataset_signature(root: Path) -> tuple:
    """Cheap cache invalidation without rehashing all scenario contents."""
    root = root.resolve()
    dataset = dataset_root(root)
    watched = [root / "docs" / "scenario_final_status.csv"]
    watched.extend(sorted(dataset.rglob("*.json")))
    return tuple((str(path.relative_to(root) if path.is_relative_to(root) else path),
                  path.stat().st_size, path.stat().st_mtime_ns)
                 for path in watched if path.exists())


@lru_cache(maxsize=8)
def _final_manifest_cached(root_label: str, validate_scenarios: bool,
                           signature: tuple) -> tuple[dict, ...]:
    del signature  # Used only as the cache key.
    root = Path(root_label)
    dataset = dataset_root(root)
    document = json.loads((dataset / "benchmark_manifest.json").read_text(encoding="utf-8"))
    if document.get("schema_version") != "2.0" or document.get("split_policy") != "family_grouped_60_10_30":
        raise ValueError("unexpected final benchmark manifest contract")
    rows = document.get("scenarios")
    if not isinstance(rows, list) or len(rows) != 100:
        raise ValueError("final benchmark manifest must contain 100 scenarios")
    ids = [row.get("scenario_id") for row in rows]
    if len(set(ids)) != 100 or any(not isinstance(sid, str) for sid in ids):
        raise ValueError("final benchmark contains duplicate or invalid scenario IDs")
    if Counter(row.get("split") for row in rows) != Counter(EXPECTED_SPLITS):
        raise ValueError("final benchmark split must be exactly 60/10/30")
    family_splits: dict[str, str] = {}
    family_counts = Counter()
    for row in rows:
        family, split = row.get("family_id"), row.get("split")
        if family not in FAMILY_FOLDERS or family not in EXPECTED_FAMILIES[split]:
            raise ValueError(f"unexpected family/split mapping: {family}/{split}")
        if family in family_splits and family_splits[family] != split:
            raise ValueError(f"family split leakage: {family}")
        family_splits[family] = split
        family_counts[family] += 1
    if set(family_counts) != set(FAMILY_FOLDERS) or any(count != 10 for count in family_counts.values()):
        raise ValueError("every final benchmark family must contain exactly 10 scenarios")
    statuses = _status_rows(root)
    enriched = []
    for source in rows:
        status = statuses.get(source["scenario_id"])
        if status is None or any(status[key] != source[key] for key in ("family_id", "split")):
            raise ValueError(f"readiness/manifest mismatch: {source['scenario_id']}")
        relative = Path(status["scenario_path"])
        if not relative.parts or relative.parts[0] != "scenarios" or ".." in relative.parts:
            raise ValueError(f"unsafe scenario path: {source['scenario_id']}")
        scenario_path = dataset / Path(*relative.parts[1:])
        if not scenario_path.is_file() or hashlib.sha256(scenario_path.read_bytes()).hexdigest() != status["scenario_sha256"]:
            raise ValueError(f"scenario file/hash mismatch: {source['scenario_id']}")
        row = dict(source) | {"state": status["state"], "state_reason": status["reason"],
                              "scenario_path": str(scenario_path.resolve()),
                              "scenario_sha256": status["scenario_sha256"]}
        if validate_scenarios:
            scenario = load_scenario(scenario_path)
            if (scenario.scenario_id, scenario.family_id, scenario.profile.profile_id) != (
                    row["scenario_id"], row["family_id"], row["profile_id"]):
                raise ValueError(f"scenario provenance mismatch: {row['scenario_id']}")
        enriched.append(row)
    return tuple(enriched)


def final_manifest(root: Path, *, validate_scenarios: bool = False) -> list[dict]:
    """Validated final manifest cached until a scenario or status file changes."""
    resolved = root.resolve()
    rows = _final_manifest_cached(str(resolved), validate_scenarios,
                                  _dataset_signature(resolved))
    return [dict(row) for row in rows]


def combined_manifest(root: Path) -> list[dict]:
    """Final dataset plus any active local scenarios outside that dataset."""
    from scenario_v2 import load_manifest
    final = ({row["scenario_id"]: row for row in final_manifest(root)}
             if manifest_path(root).exists() else {})
    for row in load_manifest(root):
        final.setdefault(row["scenario_id"], row | {
            "scenario_path": str((root / "data/scenarios" / f"{row['scenario_id']}.json").resolve()),
            "state": "local", "state_reason": "active local scenario",
        })
    return list(final.values())


def scenario_path(root: Path, scenario_id: str) -> Path:
    local = root / "data" / "scenarios" / f"{scenario_id}.json"
    if local.is_file():
        return local
    row = next((row for row in combined_manifest(root) if row["scenario_id"] == scenario_id), None)
    if row is None:
        raise ValueError(f"unknown scenario: {scenario_id}")
    return Path(row["scenario_path"])


def run_prefix(row: dict) -> tuple[str, ...]:
    # Final-dataset families use the explicit public folder mapping. Local
    # synthetic/test manifests remain isolated under their structured family ID.
    family = FAMILY_FOLDERS.get(row["family_id"], row["family_id"])
    if row["split"] == "train":
        return "treino", family
    if row["split"] == "dev":
        return "avaliacao", "desenvolvimento", family
    return "avaliacao", "teste", family
