"""Prepara linhas de treino do gate; não treina nem executa um classificador."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from annotation_workflow import (ProposalAdjudication, ScenarioAdjudication,
                                 _load_completed)
from benchmark import validate_benchmark
from models import Proposal, Scenario
from proposal_catalog import load_sources

ROOT = Path(__file__).resolve().parent.parent


class GatePredictors(BaseModel):
    """Apenas variáveis disponíveis antes da decisão; sem IDs ou rótulos."""
    critic_score: float = Field(ge=1, le=5)
    change_type: Literal["add", "move", "delete", "mixed"]
    change_count: int = Field(ge=1)
    event_importance: int = Field(ge=1, le=5)
    conflict_level: int = Field(ge=1, le=5)
    expected_impact: int = Field(ge=1, le=5)
    touches_sensitive: bool


def extract_features(scenario: Scenario, proposal: Proposal,
                     critic_score: float) -> GatePredictors:
    """Heurísticas fixas de contexto/proposta; nunca lê formulários humanos."""
    if not proposal.changes:
        raise ValueError("proposta sem mudanças não entra no gate")
    by_id = {event.id: event for event in scenario.calendar}
    kinds = {change.type for change in proposal.changes}
    change_type = next(iter(kinds)) if len(kinds) == 1 else "mixed"
    touched = [by_id[change.event_id] for change in proposal.changes
               if change.event_id in by_id]
    importance = max((event.importance for event in touched), default=3)
    sensitive = any(event.category in {"health", "supervisor_meeting", "social"}
                    for event in touched)
    overlaps = 0
    for change in proposal.changes:
        if not change.to_start:
            continue
        start = datetime.fromisoformat(change.to_start)
        if change.to_end:
            end = datetime.fromisoformat(change.to_end)
        elif change.type == "move" and change.event_id in by_id:
            original = by_id[change.event_id]
            end = start + (datetime.fromisoformat(original.end)
                           - datetime.fromisoformat(original.start))
        else:
            end = start + timedelta(hours=1)
        for event in scenario.calendar:
            if event.id == change.event_id:
                continue
            if start < datetime.fromisoformat(event.end) and datetime.fromisoformat(event.start) < end:
                overlaps += 1
    conflict = min(5, 1 + overlaps + max(0, len(proposal.changes) - 1))
    impact = min(5, 1 + max(0, len(proposal.changes) - 1)
                 + max(0, importance - 3)
                 + int(any(change.type == "delete" for change in proposal.changes))
                 + int(sensitive))
    return GatePredictors(critic_score=critic_score, change_type=change_type,
                          change_count=len(proposal.changes), event_importance=importance,
                          conflict_level=conflict, expected_impact=impact,
                          touches_sensitive=sensitive)


def build_rows(root: Path, *, split: Literal["train", "test"] = "train",
               annotator_a: str = "author_a", annotator_b: str = "author_b") -> list[dict]:
    errors, manifest = validate_benchmark(root)
    if errors:
        raise ValueError("benchmark inválido: " + "; ".join(errors))
    manifest_by_id = {row["scenario_id"]: row for row in manifest}
    sources = [source for source in load_sources(root) if source["split"] == split]
    if not sources:
        raise ValueError(f"não há propostas {split} importadas")
    scenario_a = _load_completed(root, "scenario", annotator_a)
    scenario_b = _load_completed(root, "scenario", annotator_b)
    proposal_a = _load_completed(root, "proposal", annotator_a)
    proposal_b = _load_completed(root, "proposal", annotator_b)
    rows = []
    for source in sources:
        sid, pid = source["scenario_id"], source["proposal_id"]
        manifest_row = manifest_by_id[sid]
        if (source["base_id"], source["family"], source["split"]) != (
            manifest_row["base_id"], manifest_row["family"], manifest_row["split"]
        ):
            raise ValueError(f"proveniência divergente: {pid}")
        if sid not in scenario_a or sid not in scenario_b or pid not in proposal_a or pid not in proposal_b:
            raise ValueError(f"anotações independentes incompletas: {pid}")
        if (proposal_a[pid].scenario_id, proposal_b[pid].scenario_id) != (sid, sid):
            raise ValueError(f"formulário de proposta ligado ao cenário errado: {pid}")
        scenario_path = (root / "data" / "annotation_work" / "adjudications"
                         / "scenario" / f"{sid}.json")
        proposal_path = (root / "data" / "annotation_work" / "adjudications"
                         / "proposal" / f"{pid}.json")
        if not scenario_path.is_file() or not proposal_path.is_file():
            raise ValueError(f"adjudicação em falta: {pid}")
        sa = ScenarioAdjudication.model_validate_json(scenario_path.read_text())
        pa = ProposalAdjudication.model_validate_json(proposal_path.read_text())
        if (sa.status, pa.status) != ("complete", "complete"):
            raise ValueError(f"adjudicação incompleta: {pid}")
        if sa.scenario_id != sid or pa.scenario_id != sid or pa.proposal_id != pid:
            raise ValueError(f"adjudicação divergente: {pid}")
        if set(sa.annotator_ids) != {annotator_a, annotator_b} or set(pa.annotator_ids) != {annotator_a, annotator_b}:
            raise ValueError(f"autores divergentes: {pid}")
        scenario = Scenario.model_validate_json(
            (root / "data" / "scenarios" / f"{sid}.json").read_text())
        proposal = Proposal.model_validate(source["final_proposal"])
        features = extract_features(scenario, proposal, source["critic_score"])
        assert not {"scenario_id", "proposal_id", "base_id", "family", "split", "defer"} & set(GatePredictors.model_fields)
        rows.append({
            "scenario_id": sid, "proposal_id": pid, "base_id": source["base_id"],
            "family": source["family"], "split": split,
            "run_id": source["run_id"], "configuration": source["configuration"],
            "proposer_provider": source["proposer_provider"],
            "proposer_model": source["proposer_model"],
            "critic_score": source["critic_score"],
            "features": features.model_dump(),
            "label": pa.final_decision, "label_source": "proposal_adjudication",
        })
    return sorted(rows, key=lambda row: (row["family"], row["base_id"], row["scenario_id"], row["proposal_id"]))


def grouped_gate_folds(rows: list[dict], n_splits: int = 3) -> list[dict]:
    """CV por família de treino; propostas da mesma base ficam juntas."""
    if not rows or any(row["split"] != "train" for row in rows):
        raise ValueError("folds do gate usam apenas linhas de treino")
    base_families: dict[str, set[str]] = {}
    for row in rows:
        base_families.setdefault(row["base_id"], set()).add(row["family"])
    if any(len(families) != 1 for families in base_families.values()):
        raise ValueError("uma base aparece em várias famílias")
    families = sorted({row["family"] for row in rows})
    if not 2 <= n_splits <= len(families):
        raise ValueError("n_splits incompatível com as famílias de treino")
    buckets = [set() for _ in range(n_splits)]
    for index, family in enumerate(families):
        buckets[index % n_splits].add(family)
    return [{"fold": index, "validation_families": sorted(group),
             "train_proposal_ids": sorted(row["proposal_id"] for row in rows
                                          if row["family"] not in group),
             "validation_proposal_ids": sorted(row["proposal_id"] for row in rows
                                               if row["family"] in group)}
            for index, group in enumerate(buckets)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("train", "test"), default="train")
    parser.add_argument("--unlock-test", action="store_true",
                        help="só após congelar features, modelo e hiperparâmetros")
    parser.add_argument("--annotator-a", default="author_a")
    parser.add_argument("--annotator-b", default="author_b")
    args = parser.parse_args()
    if args.split == "test" and not args.unlock_test:
        parser.error("teste reservado: usar --unlock-test apenas após congelar o gate")
    try:
        rows = build_rows(ROOT, split=args.split, annotator_a=args.annotator_a,
                          annotator_b=args.annotator_b)
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    out = ROOT / "data" / "gate_datasets" / f"{args.split}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                   encoding="utf-8")
    print(f"{len(rows)} propostas adjudicadas exportadas para {out}")


if __name__ == "__main__":
    main()
