"""Explicit consensus labels for the split-author, non-independent review protocol."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from annotation_v2 import AUTHORS, ProposalReview
from benchmark_v2 import atomic_json
from proposal_catalog_v2 import catalog

ROOT = Path(__file__).resolve().parent.parent


class JointConsensus(BaseModel):
    """One adopted label with explicit provenance; never an inter-rater pair."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["2.0"] = "2.0"
    proposal_id: str
    scenario_id: str
    review_protocol: Literal["joint_consensus"] = "joint_consensus"
    status: Literal["draft", "complete"] = "draft"
    scheduling_acceptable: Literal["yes", "no"] | None = None
    autonomy_decision: Literal["act", "defer"] | None = None
    primary_reason: str = ""
    additional_reasons: list[str] = Field(default_factory=list)
    justification: str = ""
    source_review_author: Literal["author_a", "author_b"]
    source_review_sha256: str
    adjudicated_by: str

    @model_validator(mode="after")
    def validate_decision(self):
        ProposalReview(
            proposal_id=self.proposal_id,
            scenario_id=self.scenario_id,
            annotator_id=self.source_review_author,
            status=self.status,
            scheduling_acceptable=self.scheduling_acceptable,
            autonomy_decision=self.autonomy_decision,
            primary_reason=self.primary_reason,
            additional_reasons=self.additional_reasons,
            justification=self.justification,
        )
        if self.status == "complete" and not self.adjudicated_by.strip():
            raise ValueError("complete joint consensus requires named adjudication")
        if len(self.source_review_sha256) != 64:
            raise ValueError("joint consensus requires a SHA-256 source review hash")
        try:
            int(self.source_review_sha256, 16)
        except ValueError as exc:
            raise ValueError("joint consensus source hash is not hexadecimal") from exc
        return self


def joint_path(root: Path, proposal_id: str) -> Path:
    return root / "data" / "annotations" / "joint_consensus" / f"{proposal_id}.json"


def _source_review(root: Path, proposal_id: str, author: str) -> tuple[ProposalReview, str]:
    if author not in AUTHORS:
        raise ValueError("unknown source review author")
    path = root / "data" / "annotations" / author / f"{proposal_id}.json"
    raw = path.read_bytes()
    review = ProposalReview.model_validate_json(raw)
    if review.status != "complete" or review.annotator_id != author:
        raise ValueError("joint consensus source review is not complete")
    return review, hashlib.sha256(raw).hexdigest()


def load_joint_consensus(root: Path, proposal_id: str, *,
                         scenario_id: str | None = None) -> JointConsensus:
    consensus = JointConsensus.model_validate_json(joint_path(root, proposal_id).read_text())
    review, digest = _source_review(root, proposal_id, consensus.source_review_author)
    if (consensus.proposal_id, consensus.scenario_id) != (proposal_id, review.scenario_id):
        raise ValueError("joint consensus provenance mismatch")
    if scenario_id is not None and consensus.scenario_id != scenario_id:
        raise ValueError("joint consensus scenario does not match proposal catalogue")
    if consensus.source_review_sha256 != digest:
        raise ValueError("joint consensus is stale against its source review")
    return consensus


def bootstrap(root: Path, *, adjudicated_by: str, refresh: bool = False) -> dict:
    """Adopt the sole completed split-author review without inventing a second review."""
    created = refreshed = skipped = 0
    for source in catalog(root):
        completed: list[tuple[ProposalReview, str]] = []
        for author in AUTHORS:
            path = root / "data" / "annotations" / author / f"{source['proposal_id']}.json"
            if not path.exists():
                continue
            raw = path.read_bytes()
            review = ProposalReview.model_validate_json(raw)
            if review.status == "complete":
                if (review.proposal_id, review.scenario_id, review.annotator_id) != (
                        source["proposal_id"], source["scenario_id"], author):
                    raise ValueError("source review provenance mismatch")
                completed.append((review, hashlib.sha256(raw).hexdigest()))
        if len(completed) != 1:
            skipped += 1
            continue
        review, digest = completed[0]
        consensus = JointConsensus(
            proposal_id=review.proposal_id,
            scenario_id=review.scenario_id,
            status="complete",
            scheduling_acceptable=review.scheduling_acceptable,
            autonomy_decision=review.autonomy_decision,
            primary_reason=review.primary_reason,
            additional_reasons=review.additional_reasons,
            justification=review.justification,
            source_review_author=review.annotator_id,
            source_review_sha256=digest,
            adjudicated_by=adjudicated_by,
        )
        path = joint_path(root, review.proposal_id)
        if path.exists() and not refresh:
            skipped += 1
            continue
        existed = path.exists()
        atomic_json(path, consensus.model_dump())
        refreshed += int(existed)
        created += int(not existed)
    return {"created": created, "refreshed": refreshed, "skipped": skipped}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create transparent joint-consensus labels")
    parser.add_argument("--adjudicated-by", required=True,
                        help="recorded human/process name, e.g. author_a_and_author_b")
    parser.add_argument("--refresh", action="store_true",
                        help="refresh existing joint labels after an intentional source-review edit")
    args = parser.parse_args()
    print(bootstrap(ROOT, adjudicated_by=args.adjudicated_by, refresh=args.refresh))


if __name__ == "__main__":
    main()
