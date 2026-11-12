"""Importa propostas finais de B sem expor o histórico aos anotadores."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from benchmark import validate_benchmark
from models import Proposal

ROOT = Path(__file__).resolve().parent.parent


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def import_result(root: Path, result_path: Path) -> Path:
    """Só importa propostas B aceites; idempotente para o mesmo registo."""
    errors, manifest = validate_benchmark(root)
    if errors:
        raise ValueError("benchmark inválido: " + "; ".join(errors))
    raw = result_path.read_bytes()
    record = json.loads(raw)
    if record.get("configuration") != "B" or record.get("status") != "proposal_ready":
        raise ValueError("é necessário um resultado B com status proposal_ready")
    if record.get("critic_accepted") is not True or record.get("final_score") is None:
        raise ValueError("o Critic deve ter aceite a proposta final")
    if (not isinstance(record["final_score"], (int, float))
            or isinstance(record["final_score"], bool)
            or not 1 <= record["final_score"] <= 5):
        raise ValueError("score final do Critic inválido")
    proposal = Proposal.model_validate(record.get("final_proposal"))
    sid = record["scenario_id"]
    row = next((entry for entry in manifest if entry["scenario_id"] == sid), None)
    if row is None or record.get("family") != row["family"]:
        raise ValueError("cenário ou família divergente do manifesto")
    if record.get("split") not in (None, row["split"]):
        raise ValueError("split divergente do manifesto")
    history = record.get("iterations")
    if not isinstance(history, list) or not history:
        raise ValueError("histórico de refinamento em falta")
    last = next((step for step in reversed(history) if step.get("proposal") is not None), None)
    if last is None or Proposal.model_validate(last["proposal"]) != proposal:
        raise ValueError("proposta final difere do histórico")
    run_id = record.get("run_id") or result_path.parent.parent.name
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id em falta")
    identity = {"run_id": run_id, "scenario_id": sid,
                "final_proposal": proposal.model_dump()}
    proposal_id = "p_" + hashlib.sha256(_canonical(identity)).hexdigest()[:20]
    source = {
        "proposal_id": proposal_id, "scenario_id": sid, "base_id": row["base_id"],
        "family": row["family"], "split": row["split"], "category": row["category"],
        "run_id": run_id, "configuration": "B",
        "source_status": "proposal_ready", "critic_accepted": True,
        "experiment_id": record.get("experiment_id"),
        "repeat_index": record.get("repeat_index", 0),
        "proposer_provider": record.get("proposer_provider"),
        "proposer_model": record.get("proposer_model"),
        "proposer_generation_config": record.get("proposer_generation_config"),
        "critic_provider": record.get("critic_provider"),
        "critic_model": record.get("critic_model"),
        "critic_generation_config": record.get("critic_generation_config"),
        "critic_settings": record.get("critic_settings"),
        "critic_score": record["final_score"],
        "final_proposal": proposal.model_dump(),
        "refinement_history": history,
        "source_result_sha256": hashlib.sha256(raw).hexdigest(),
    }
    out = root / "data" / "proposal_sources" / f"{proposal_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(source, ensure_ascii=False, indent=2) + "\n"
    if out.exists():
        if json.loads(out.read_text(encoding="utf-8")) != source:
            raise ValueError(f"colisão ou alteração da fonte: {proposal_id}")
    else:
        out.write_text(content, encoding="utf-8")
    return out


def load_sources(root: Path) -> list[dict]:
    sources = []
    for path in sorted((root / "data" / "proposal_sources").glob("*.json")):
        source = json.loads(path.read_text(encoding="utf-8"))
        if source.get("proposal_id") != path.stem:
            raise ValueError(f"proposal_id divergente em {path.name}")
        if source.get("configuration") != "B" or source.get("source_status") != "proposal_ready" or source.get("critic_accepted") is not True:
            raise ValueError(f"fonte não elegível para gate: {path.name}")
        Proposal.model_validate(source["final_proposal"])
        identity = {"run_id": source["run_id"], "scenario_id": source["scenario_id"],
                    "final_proposal": source["final_proposal"]}
        expected_id = "p_" + hashlib.sha256(_canonical(identity)).hexdigest()[:20]
        if expected_id != path.stem:
            raise ValueError(f"identidade da proposta divergente: {path.name}")
        sources.append(source)
    return sources


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path, help="JSON de uma execução B")
    args = parser.parse_args()
    try:
        path = import_result(ROOT, args.result)
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    print(f"Proposta importada: {path.name}")


if __name__ == "__main__":
    main()
