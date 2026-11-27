"""Export labelled, applicable B v2 proposals; no classifier training."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from annotation_v2 import ProposalConsensus, _consensus_path, pair
from calendar_v2 import simulate
from models import Proposal
from proposal_catalog_v2 import catalog, training_catalog_audit
from scenario_v2 import load_scenario
from final_dataset_v2 import combined_manifest, scenario_path
from joint_consensus_v2 import load_joint_consensus

ROOT = Path(__file__).resolve().parent.parent


def features(scenario, proposal: Proposal, score: float) -> dict:
    """Only proposal/context variables available before the human label."""
    by_id = {event.id: event for event in scenario.calendar.events}
    touched = [by_id[c.event_id] for c in proposal.changes if c.event_id in by_id]
    types = {c.type for c in proposal.changes}
    return {"critic_score": score, "change_count": len(proposal.changes),
            "change_type": next(iter(types)) if len(types) == 1 else "mixed",
            "max_touched_importance": max((e.importance for e in touched), default=3),
            "touches_fixed": any(e.fixed for e in touched),
            "touches_third_party": any(any(p != "user" for p in e.participants) for e in touched),
            "deletes_event": any(c.type == "delete" for c in proposal.changes),
            "moves_event": any(c.type == "move" for c in proposal.changes),
            "adds_event": any(c.type == "add" for c in proposal.changes)}


def build_rows(root: Path, *, split: str = "train", unlock_test: bool = False,
               label_protocol: str = "independent_adjudication") -> tuple[list[dict], list[dict]]:
    if split not in {"train", "dev", "test"}:
        raise ValueError("split must be train, dev or test")
    if split == "test" and not unlock_test:
        raise ValueError("test remains locked until model and evaluation policy are frozen")
    if label_protocol not in {"independent_adjudication", "joint_consensus"}:
        raise ValueError("unknown label protocol")
    manifest = combined_manifest(root)
    family_split = {}
    for entry in manifest:
        family_split.setdefault(entry["family_id"], entry["split"])
        if family_split[entry["family_id"]] != entry["split"]:
            raise ValueError("family split leakage")
    rows, exclusions = [], []
    if split == "train":
        audit = training_catalog_audit(root)
        sources = audit["active"]
        exclusions.extend({"proposal_id": item["proposal_id"],
                           "reason": "source_run_integrity_failed"}
                          for item in audit["quarantined"])
    else:
        sources = catalog(root)
    for source in sources:
        if source["split"] != split:
            continue
        pid = source["proposal_id"]
        reason = None
        scenario = load_scenario(scenario_path(root, source["scenario_id"]))
        proposal = Proposal.model_validate(source["final_proposal"])
        _, validation = simulate(scenario, proposal)
        if not proposal.changes:
            reason = "no_op_requires_separate_eligibility_policy"
        elif not validation["valid"]:
            reason = "technical_validation_failed"
        elif source["source_status"] != "proposal_ready" or source["critic_accepted"] is not True:
            reason = "critic_not_accepted_or_run_not_ready"
        elif not isinstance(source["critic_score"], (int, float)) or not 1 <= source["critic_score"] <= 5:
            reason = "critic_score_missing"
        else:
            consensus = None
            try:
                if label_protocol == "joint_consensus":
                    consensus = load_joint_consensus(root, pid, scenario_id=source["scenario_id"])
                    hashes = None
                else:
                    _, _, hashes = pair(root, pid)
                    path = _consensus_path(root, pid)
                    consensus = ProposalConsensus.model_validate_json(path.read_text())
            except (ValueError, OSError):
                reason = ("joint_consensus_missing_or_stale" if label_protocol == "joint_consensus"
                          else "independent_reviews_or_consensus_missing")
            else:
                if hashes is not None and consensus.original_review_sha256 != hashes:
                    reason = "consensus_stale_against_original_reviews"
                elif consensus.status != "complete":
                    reason = "consensus_incomplete"
                elif consensus.scheduling_acceptable != "yes":
                    reason = "scheduling_rejected"
                elif consensus.autonomy_decision not in {"act", "defer"}:
                    reason = "autonomy_label_missing"
                else:
                    predictors = features(scenario, proposal, source["critic_score"])
                    assert not {"proposal_id", "scenario_id", "family_id", "profile_id",
                                "primary_reason", "additional_reasons", "justification", "label"} & predictors.keys()
                    rows.append({"proposal_id": pid, "scenario_id": source["scenario_id"],
                                 "family_id": source["family_id"], "profile_id": source["profile_id"],
                                 "split": split, "run_id": source["run_id"],
                                 "configuration": source["configuration"],
                                 "features": predictors, "critic_score": source["critic_score"],
                                 "label": consensus.autonomy_decision,
                                 "label_source": ("v2_joint_consensus" if label_protocol == "joint_consensus"
                                                  else "v2_proposal_adjudication"),
                                 "review_protocol": label_protocol})
        if reason:
            exclusions.append({"proposal_id": pid, "reason": reason})
    return rows, exclusions


def grouped_folds(rows: list[dict], n_splits: int) -> list[dict]:
    if any(row["split"] != "train" for row in rows):
        raise ValueError("grouped folds use train only")
    families = sorted({row["family_id"] for row in rows})
    if not 2 <= n_splits <= len(families):
        raise ValueError("insufficient training families")
    return [{"fold": i, "validation_families": families[i::n_splits],
             "train_proposal_ids": [row["proposal_id"] for row in rows if row["family_id"] not in families[i::n_splits]],
             "validation_proposal_ids": [row["proposal_id"] for row in rows if row["family_id"] in families[i::n_splits]]}
            for i in range(n_splits)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Export v2 gate examples; no model training")
    parser.add_argument("--split", choices=("train", "dev", "test"), default="train")
    parser.add_argument("--unlock-test", action="store_true",
                        help="only after freezing features, classifier and evaluation policy")
    parser.add_argument("--label-protocol",
                        choices=("independent_adjudication", "joint_consensus"),
                        default="independent_adjudication")
    args = parser.parse_args()
    rows, exclusions = build_rows(ROOT, split=args.split, unlock_test=args.unlock_test,
                                  label_protocol=args.label_protocol)
    out = ROOT / "data" / "gate_datasets" / f"{args.split}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    report = out.with_suffix(".exclusions.json")
    report.write_text(json.dumps(exclusions, indent=2), encoding="utf-8")
    print(f"{len(rows)} eligible examples; {len(exclusions)} exclusions: {out}")


if __name__ == "__main__":
    main()
