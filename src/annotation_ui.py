"""Small local UI adapter over the existing annotation workflow and JSON files.

No model calls, labels, or benchmark transformations live here. Streamlit imports
this module; tests exercise it without starting a server.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from annotation_workflow import (
    ProposalAdjudication, ProposalAnnotation, ScenarioAdjudication,
    ScenarioAnnotation, _load_completed, _safe_id, compare,
    prepare_adjudications, prepare_proposals, prepare_scenarios,
    validate_adjudications,
)
from benchmark import validate_benchmark
from models import Proposal

ROOT = Path(__file__).resolve().parent.parent
AUTHORS = ("author_a", "author_b")
Phase = Literal["scenario", "proposal"]
FORM_MODELS = {"scenario": ScenarioAnnotation, "proposal": ProposalAnnotation}
ADJ_MODELS = {"scenario": ScenarioAdjudication, "proposal": ProposalAdjudication}


def _author(author: str) -> str:
    if author not in AUTHORS:
        raise ValueError("avaliador desconhecido")
    return author


def _phase(phase: str) -> Phase:
    if phase not in FORM_MODELS:
        raise ValueError("fase desconhecida")
    return phase


def _item_id(item_id: str) -> str:
    return _safe_id(item_id)


def _path(root: Path, author: str, phase: Phase, kind: str, item_id: str) -> Path:
    return root / "data" / "annotation_work" / _author(author) / _phase(phase) / kind / f"{_item_id(item_id)}.json"


def _adjudication_path(root: Path, phase: Phase, item_id: str) -> Path:
    return root / "data" / "annotation_work" / "adjudications" / _phase(phase) / f"{_item_id(item_id)}.json"


def _read(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def _safe_packet(phase: Phase, raw: dict) -> dict:
    """Allowlist protects blind annotation even if a packet has extra keys."""
    def scenario(data: dict) -> dict:
        return {key: data[key] for key in ("scenario_id", "user_request", "now", "calendar", "profile")}

    if phase == "scenario":
        return scenario(raw)
    reference = raw["scenario_reference"]
    return {"proposal_id": raw["proposal_id"],
            "scenario": scenario(raw["scenario"]),
            "scenario_reference": {key: reference[key] for key in (
                "hard_constraints", "acceptable_outcomes", "impact_factors",
                "ambiguity_present", "ambiguity_notes")},
            "final_proposal": Proposal.model_validate(raw["final_proposal"]).model_dump()}


def prepare(root: Path, author: str, phase: Phase) -> int:
    _author(author)
    _phase(phase)
    return (prepare_scenarios if phase == "scenario" else prepare_proposals)(root, author)


def items(root: Path, author: str, phase: Phase) -> list[dict]:
    """List only the selected author's forms; bad forms remain visible as errors."""
    _author(author)
    _phase(phase)
    if phase == "scenario":
        errors, manifest = validate_benchmark(root)
        if errors:
            raise ValueError("benchmark inválido: " + "; ".join(errors))
        ids = sorted(row["scenario_id"] for row in manifest)
    else:
        ids = sorted(path.stem for path in
                     (root / "data" / "annotation_work" / author / phase / "forms").glob("*.json"))
    result = []
    for item_id in ids:
        path = _path(root, author, phase, "forms", item_id)
        if not path.exists():
            state = "not_started"
        else:
            try:
                raw, _ = _read(path)
                form = FORM_MODELS[phase].model_validate(raw)
                if form.annotator_id != author or (form.scenario_id if phase == "scenario" else form.proposal_id) != item_id:
                    raise ValueError("identificadores divergentes")
                fields = form.model_dump(exclude={"scenario_id", "proposal_id", "annotator_id", "status", "annotation_version"})
                has_work = any(value is not None and value != "" and value != []
                               for value in fields.values())
                state = "complete" if form.status == "complete" else ("draft" if has_work else "not_started")
            except (ValidationError, ValueError, KeyError, OSError, json.JSONDecodeError):
                state = "needs_correction"
        result.append({"id": item_id, "state": state})
    return result


def load_item(root: Path, author: str, phase: Phase, item_id: str) -> tuple[dict, dict, str]:
    """Return only the chosen author's safe packet, validated form and revision."""
    _author(author)
    _phase(phase)
    if item_id not in {row["id"] for row in items(root, author, phase)}:
        raise ValueError("item indisponível para este avaliador")
    packet, _ = _read(_path(root, author, phase, "packets", item_id))
    raw, digest = _read(_path(root, author, phase, "forms", item_id))
    form = FORM_MODELS[phase].model_validate(raw)
    if form.annotator_id != author or (form.scenario_id if phase == "scenario" else form.proposal_id) != item_id:
        raise ValueError("formulário associado a outro item/avaliador")
    if phase == "proposal" and form.scenario_id != packet["scenario"]["scenario_id"]:
        raise ValueError("proposta associada a outro cenário")
    return _safe_packet(phase, packet), form.model_dump(), digest


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _save(path: Path, data: dict, expected_revision: str, *, confirm_completed: bool,
          model: type, expected_id: str, author: str | None = None) -> str:
    old, revision = _read(path)
    if revision != expected_revision:
        raise ValueError("o ficheiro mudou noutra sessão; recarregue antes de guardar")
    if old.get("status") == "complete" and old != data and not confirm_completed:
        raise ValueError("a anotação concluída exige confirmação explícita para ser alterada")
    form = model.model_validate(data)
    key = "proposal_id" if model in (ProposalAnnotation, ProposalAdjudication) else "scenario_id"
    if getattr(form, key) != expected_id:
        raise ValueError("identificador do formulário divergente")
    if author is not None and form.annotator_id != author:
        raise ValueError("formulário associado a outro avaliador")
    if author is None and set(form.annotator_ids) != set(AUTHORS):
        raise ValueError("adjudicação requer os dois autores")
    output = form.model_dump()
    if output == old:
        return revision
    _atomic_write(path, output)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_form(root: Path, author: str, phase: Phase, item_id: str, data: dict,
              expected_revision: str, *, confirm_completed: bool = False) -> str:
    # load_item verifies packet/form ownership and phase availability.
    packet, saved, current = load_item(root, author, phase, item_id)
    if current != expected_revision:
        raise ValueError("o ficheiro mudou noutra sessão; recarregue antes de guardar")
    adjudication = _adjudication_path(root, phase, item_id)
    if adjudication.is_file():
        previous_consensus, _ = _read(adjudication)
        if previous_consensus.get("status") == "complete" and data != saved:
            raise ValueError("este item já foi adjudicado; a anotação individual está fechada")
    if phase == "proposal" and data.get("scenario_id") != packet["scenario"]["scenario_id"]:
        raise ValueError("cenário da proposta divergente")
    return _save(_path(root, author, phase, "forms", item_id), data,
                 expected_revision, confirm_completed=confirm_completed,
                 model=FORM_MODELS[phase], expected_id=item_id, author=author)


def paired_ids(root: Path, phase: Phase) -> list[str]:
    _phase(phase)
    a = _load_completed(root, phase, AUTHORS[0])
    b = _load_completed(root, phase, AUTHORS[1])
    return sorted(a.keys() & b.keys())


def comparison(root: Path, phase: Phase) -> dict:
    if not paired_ids(root, phase):
        raise ValueError("ambos os autores devem concluir pelo menos um item da fase")
    report = compare(root, phase, *AUTHORS)
    report.pop("unpaired_complete", None)  # do not show the other author's progress
    return report


def load_pair(root: Path, phase: Phase, item_id: str) -> tuple[dict, dict]:
    if item_id not in paired_ids(root, phase):
        raise ValueError("ambos os autores devem concluir este item antes da comparação")
    a, _ = _read(_path(root, AUTHORS[0], phase, "forms", item_id))
    b, _ = _read(_path(root, AUTHORS[1], phase, "forms", item_id))
    return FORM_MODELS[phase].model_validate(a).model_dump(), FORM_MODELS[phase].model_validate(b).model_dump()


def load_adjudication(root: Path, phase: Phase, item_id: str) -> tuple[dict, str]:
    if item_id not in paired_ids(root, phase):
        raise ValueError("ambos os autores devem concluir este item antes da adjudicação")
    prepare_adjudications(root, phase, *AUTHORS)
    raw, digest = _read(_adjudication_path(root, phase, item_id))
    form = ADJ_MODELS[phase].model_validate(raw)
    if set(form.annotator_ids) != set(AUTHORS):
        raise ValueError("avaliadores da adjudicação divergentes")
    return form.model_dump(), digest


def save_adjudication(root: Path, phase: Phase, item_id: str, data: dict,
                      expected_revision: str, *, confirm_completed: bool = False) -> str:
    if item_id not in paired_ids(root, phase):
        raise ValueError("ambos os autores devem concluir este item antes da adjudicação")
    previous, current = load_adjudication(root, phase, item_id)
    if current != expected_revision:
        raise ValueError("o consenso mudou noutra sessão; recarregue antes de guardar")
    if phase == "proposal" and data.get("scenario_id") != previous["scenario_id"]:
        raise ValueError("cenário da adjudicação divergente")
    return _save(_adjudication_path(root, phase, item_id), data,
                 expected_revision, confirm_completed=confirm_completed,
                 model=ADJ_MODELS[phase], expected_id=item_id)


def adjudication_progress(root: Path, phase: Phase) -> dict:
    return validate_adjudications(root, phase, *AUTHORS)
