"""Anotação cega em duas fases, comparação e adjudicação humana explícita."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from benchmark import validate_benchmark
from models import Profile, Scenario
from proposal_catalog import load_sources

ROOT = Path(__file__).resolve().parent.parent
Phase = Literal["scenario", "proposal"]
Decision = Literal["act", "defer"]


def _text_items(items: list[str]) -> bool:
    return any(isinstance(item, str) and item.strip() for item in items)


class ScenarioAnnotation(BaseModel):
    scenario_id: str
    annotator_id: str
    status: Literal["draft", "complete"] = "draft"
    hard_constraints: list[str] = Field(default_factory=list)
    acceptable_outcomes: list[str] = Field(default_factory=list)
    impact_factors: list[str] = Field(default_factory=list)
    ambiguity_present: bool | None = None
    ambiguity_notes: str = ""

    @model_validator(mode="after")
    def _complete(self):
        if self.status == "complete" and (
            not _text_items(self.acceptable_outcomes) or self.ambiguity_present is None
            or (self.ambiguity_present and not self.ambiguity_notes.strip())
        ):
            raise ValueError("cenário completo requer resultados aceitáveis e avaliação de ambiguidade")
        return self


class ProposalAnnotation(BaseModel):
    proposal_id: str
    scenario_id: str
    annotator_id: str
    status: Literal["draft", "complete"] = "draft"
    decision: Decision | None = None
    decision_rationale: str = ""
    scheduling_acceptable: bool | None = None
    intervention_impact: int | None = Field(default=None, ge=1, le=5)
    intervention_risk: int | None = Field(default=None, ge=1, le=5)
    risk_factors: list[str] = Field(default_factory=list)
    ambiguity_notes: str = ""

    @model_validator(mode="after")
    def _complete(self):
        if self.status == "complete" and (
            self.decision is None or not self.decision_rationale.strip()
            or self.scheduling_acceptable is None or self.intervention_impact is None
            or self.intervention_risk is None
        ):
            raise ValueError("proposta completa requer rótulo, razão, adequação, impacto e risco")
        if self.status == "complete" and self.decision == "act" and self.scheduling_acceptable is not True:
            raise ValueError("act exige proposta de scheduling aceitável")
        return self


class ScenarioAdjudication(BaseModel):
    scenario_id: str
    annotator_ids: list[str]
    status: Literal["draft", "complete"] = "draft"
    hard_constraints: list[str] = Field(default_factory=list)
    acceptable_outcomes: list[str] = Field(default_factory=list)
    impact_factors: list[str] = Field(default_factory=list)
    ambiguity_present: bool | None = None
    ambiguity_notes: str = ""
    resolution_rationale: str = ""
    resolved_by: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _complete(self):
        if self.status == "complete" and (
            not _text_items(self.acceptable_outcomes) or self.ambiguity_present is None
            or (self.ambiguity_present and not self.ambiguity_notes.strip())
            or not self.resolution_rationale.strip()
            or len(set(self.annotator_ids)) != 2
            or set(self.resolved_by) != set(self.annotator_ids)
        ):
            raise ValueError("adjudicação de cenário incompleta")
        return self


class ProposalAdjudication(BaseModel):
    proposal_id: str
    scenario_id: str
    annotator_ids: list[str]
    status: Literal["draft", "complete"] = "draft"
    final_decision: Decision | None = None
    decision_rationale: str = ""
    scheduling_acceptable: bool | None = None
    intervention_impact: int | None = Field(default=None, ge=1, le=5)
    intervention_risk: int | None = Field(default=None, ge=1, le=5)
    risk_factors: list[str] = Field(default_factory=list)
    resolved_by: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _complete(self):
        if self.status == "complete" and (
            self.final_decision is None or not self.decision_rationale.strip()
            or self.scheduling_acceptable is None or self.intervention_impact is None
            or self.intervention_risk is None
            or len(set(self.annotator_ids)) != 2
            or set(self.resolved_by) != set(self.annotator_ids)
        ):
            raise ValueError("adjudicação de proposta incompleta")
        if self.status == "complete" and self.final_decision == "act" and self.scheduling_acceptable is not True:
            raise ValueError("act exige proposta de scheduling aceitável")
        return self


def _safe_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("ID deve conter apenas letras, números, _ ou -")
    return value


def _write_if_absent(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")


def _scenario_packet(scenario: Scenario, profile: Profile) -> dict:
    """Lista positiva: sem split, pré-rótulo, outputs dos agentes ou família."""
    return {"scenario_id": scenario.id, "user_request": scenario.user_request,
            "now": scenario.now, "calendar": [e.model_dump() for e in scenario.calendar],
            "profile": profile.model_dump()}


def prepare_scenarios(root: Path, annotator_id: str) -> int:
    annotator_id = _safe_id(annotator_id)
    errors, rows = validate_benchmark(root)
    if errors:
        raise ValueError("benchmark inválido: " + "; ".join(errors))
    profile = Profile.model_validate_json((root / "data" / "profile.json").read_text())
    work = root / "data" / "annotation_work" / annotator_id / "scenario"
    for row in rows:
        sid = row["scenario_id"]
        scenario = Scenario.model_validate_json(
            (root / "data" / "scenarios" / f"{sid}.json").read_text())
        _write_if_absent(work / "packets" / f"{sid}.json", _scenario_packet(scenario, profile))
        form = ScenarioAnnotation(scenario_id=sid, annotator_id=annotator_id)
        _write_if_absent(work / "forms" / f"{sid}.json", form.model_dump())
    return len(rows)


def prepare_proposals(root: Path, annotator_id: str) -> int:
    annotator_id = _safe_id(annotator_id)
    profile = Profile.model_validate_json((root / "data" / "profile.json").read_text())
    sources = load_sources(root)
    work = root / "data" / "annotation_work" / annotator_id / "proposal"
    references = {}
    for source in sources:
        sid = source["scenario_id"]
        path = root / "data" / "annotation_work" / "adjudications" / "scenario" / f"{sid}.json"
        if not path.is_file():
            raise ValueError(f"anotar e adjudicar primeiro o cenário {sid}")
        reference = ScenarioAdjudication.model_validate_json(path.read_text(encoding="utf-8"))
        if reference.status != "complete" or reference.scenario_id != sid:
            raise ValueError(f"adjudicação de cenário incompleta: {sid}")
        if any(sid not in _load_completed(root, "scenario", author)
               for author in reference.annotator_ids):
            raise ValueError(f"anotações independentes do cenário incompletas: {sid}")
        references[sid] = {
            "hard_constraints": reference.hard_constraints,
            "acceptable_outcomes": reference.acceptable_outcomes,
            "impact_factors": reference.impact_factors,
            "ambiguity_present": reference.ambiguity_present,
            "ambiguity_notes": reference.ambiguity_notes,
        }
    for source in sources:
        sid, pid = source["scenario_id"], source["proposal_id"]
        scenario = Scenario.model_validate_json(
            (root / "data" / "scenarios" / f"{sid}.json").read_text())
        packet = {"proposal_id": pid, "scenario": _scenario_packet(scenario, profile),
                  "scenario_reference": references[sid],
                  "final_proposal": source["final_proposal"]}
        _write_if_absent(work / "packets" / f"{pid}.json", packet)
        form = ProposalAnnotation(proposal_id=pid, scenario_id=sid,
                                  annotator_id=annotator_id)
        _write_if_absent(work / "forms" / f"{pid}.json", form.model_dump())
    return len(sources)


def _load_completed(root: Path, phase: Phase, annotator_id: str) -> dict[str, BaseModel]:
    annotator_id = _safe_id(annotator_id)
    model = ScenarioAnnotation if phase == "scenario" else ProposalAnnotation
    forms = {}
    path = root / "data" / "annotation_work" / annotator_id / phase / "forms"
    for item in path.glob("*.json"):
        form = model.model_validate_json(item.read_text(encoding="utf-8"))
        expected = form.scenario_id if phase == "scenario" else form.proposal_id
        if expected != item.stem or form.annotator_id != annotator_id:
            raise ValueError(f"identificadores divergentes: {item.name}")
        if form.status == "complete":
            forms[expected] = form
    return forms


def cohens_kappa(pairs: list[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    p_a = sum(a == "act" for a, _ in pairs) / n
    p_b = sum(b == "act" for _, b in pairs) / n
    expected = p_a * p_b + (1 - p_a) * (1 - p_b)
    return None if expected == 1 else round((observed - expected) / (1 - expected), 4)


def compare(root: Path, phase: Phase, annotator_a: str, annotator_b: str) -> dict:
    if annotator_a == annotator_b:
        raise ValueError("são necessários dois avaliadores diferentes")
    a = _load_completed(root, phase, annotator_a)
    b = _load_completed(root, phase, annotator_b)
    ids = sorted(a.keys() & b.keys())
    result = {"phase": phase, "annotators": [annotator_a, annotator_b],
              "complete_pairs": len(ids), "unpaired_complete": sorted(a.keys() ^ b.keys())}
    if phase == "scenario":
        def normalized(values: list[str]) -> set[str]:
            return {" ".join(value.lower().split()) for value in values}

        result.update(ambiguity_disagreements=[sid for sid in ids
                                              if a[sid].ambiguity_present != b[sid].ambiguity_present],
                      outcome_text_review_required=[sid for sid in ids
                                                    if normalized(a[sid].acceptable_outcomes)
                                                    != normalized(b[sid].acceptable_outcomes)],
                      hard_constraint_text_review_required=[sid for sid in ids
                                                            if normalized(a[sid].hard_constraints)
                                                            != normalized(b[sid].hard_constraints)])
    else:
        pairs = [(a[sid].decision, b[sid].decision) for sid in ids]
        agreements = sum(left == right for left, right in pairs)
        result.update(agreement_count=agreements,
                      observed_agreement=round(agreements / len(ids), 4) if ids else None,
                      cohens_kappa=cohens_kappa(pairs),
                      decision_disagreements=[sid for sid, (left, right) in zip(ids, pairs)
                                              if left != right],
                      scheduling_disagreements=[sid for sid in ids
                                                if a[sid].scheduling_acceptable
                                                != b[sid].scheduling_acceptable],
                      rating_mean_absolute_difference={
                          field: round(sum(abs(getattr(a[sid], field) - getattr(b[sid], field))
                                           for sid in ids) / len(ids), 2) if ids else None
                          for field in ("intervention_impact", "intervention_risk")})
    return result


def prepare_adjudications(root: Path, phase: Phase, annotator_a: str,
                          annotator_b: str) -> int:
    a = _load_completed(root, phase, annotator_a)
    b = _load_completed(root, phase, annotator_b)
    ids = sorted(a.keys() & b.keys())
    for item_id in ids:
        path = root / "data" / "annotation_work" / "adjudications" / phase / f"{item_id}.json"
        if phase == "scenario":
            form = ScenarioAdjudication(scenario_id=item_id,
                                        annotator_ids=[annotator_a, annotator_b])
        else:
            if a[item_id].scenario_id != b[item_id].scenario_id:
                raise ValueError(f"cenário divergente na proposta: {item_id}")
            form = ProposalAdjudication(proposal_id=item_id,
                                        scenario_id=a[item_id].scenario_id,
                                        annotator_ids=[annotator_a, annotator_b])
        _write_if_absent(path, form.model_dump())
    return len(ids)


def validate_adjudications(root: Path, phase: Phase, annotator_a: str,
                           annotator_b: str) -> dict:
    a = _load_completed(root, phase, annotator_a)
    b = _load_completed(root, phase, annotator_b)
    paired = sorted(a.keys() & b.keys())
    model = ScenarioAdjudication if phase == "scenario" else ProposalAdjudication
    complete, pending = [], []
    for item_id in paired:
        path = root / "data" / "annotation_work" / "adjudications" / phase / f"{item_id}.json"
        if not path.is_file():
            pending.append(item_id)
            continue
        form = model.model_validate_json(path.read_text(encoding="utf-8"))
        expected = form.scenario_id if phase == "scenario" else form.proposal_id
        if expected != item_id or set(form.annotator_ids) != {annotator_a, annotator_b}:
            raise ValueError(f"adjudicação divergente: {item_id}")
        if phase == "proposal" and form.scenario_id != a[item_id].scenario_id:
            raise ValueError(f"cenário divergente na adjudicação: {item_id}")
        (complete if form.status == "complete" else pending).append(item_id)
    return {"phase": phase, "complete": complete, "pending": pending}


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare-scenarios", "prepare-proposals"):
        p = sub.add_parser(command)
        p.add_argument("annotator_id")
    for command in ("compare", "prepare-adjudications", "validate-adjudications"):
        p = sub.add_parser(command)
        p.add_argument("phase", choices=("scenario", "proposal"))
        p.add_argument("annotator_a")
        p.add_argument("annotator_b")
    args = parser.parse_args()
    try:
        if args.command == "prepare-scenarios":
            print(f"{prepare_scenarios(ROOT, args.annotator_id)} cenários preparados")
        elif args.command == "prepare-proposals":
            print(f"{prepare_proposals(ROOT, args.annotator_id)} propostas preparadas")
        elif args.command == "compare":
            print(json.dumps(compare(ROOT, args.phase, args.annotator_a,
                                     args.annotator_b), indent=2))
        elif args.command == "prepare-adjudications":
            print(f"{prepare_adjudications(ROOT, args.phase, args.annotator_a,
                                           args.annotator_b)} templates preparados")
        else:
            print(json.dumps(validate_adjudications(ROOT, args.phase,
                                                    args.annotator_a, args.annotator_b), indent=2))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
