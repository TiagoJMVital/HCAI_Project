"""Direct, independent proposal evaluation for the active workflow."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agreement import cohens_kappa
from benchmark_v2 import atomic_json
from proposal_catalog_v2 import catalog

AUTHORS = ("author_a", "author_b")
DEFER_REASONS = ("clarification_required", "confirmation_required", "high_impact",
                 "third_party_impact", "preference_conflict")


class ProposalReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["2.0"] = "2.0"
    proposal_id: str
    scenario_id: str
    annotator_id: Literal["author_a", "author_b"]
    status: Literal["draft", "complete"] = "draft"
    scheduling_acceptable: Literal["yes", "no"] | None = None
    autonomy_decision: Literal["act", "defer"] | None = None
    primary_reason: str = ""
    additional_reasons: list[str] = Field(default_factory=list)
    justification: str = ""

    @model_validator(mode="after")
    def complete_fields(self):
        if self.scheduling_acceptable == "no" and self.autonomy_decision is not None:
            raise ValueError("unacceptable scheduling cannot receive an autonomy label")
        if self.autonomy_decision == "defer":
            if self.primary_reason and self.primary_reason not in DEFER_REASONS:
                raise ValueError("unknown primary defer reason")
            if any(x not in DEFER_REASONS for x in self.additional_reasons):
                raise ValueError("unknown additional defer reason")
            if len(self.additional_reasons) != len(set(self.additional_reasons)) or self.primary_reason in self.additional_reasons:
                raise ValueError("duplicate defer reasons")
        elif self.additional_reasons:
            raise ValueError("additional defer reasons require a defer decision")
        if self.status == "complete":
            if self.scheduling_acceptable is None or not self.justification.strip() or not self.primary_reason.strip():
                raise ValueError("completed review requires acceptability, primary reason and justification")
            if self.scheduling_acceptable == "yes" and self.autonomy_decision is None:
                raise ValueError("acceptable scheduling requires act or defer")
            if self.scheduling_acceptable == "no" and self.autonomy_decision is not None:
                raise ValueError("quality rejection must have no autonomy label")
        return self


class ProposalConsensus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["2.0"] = "2.0"
    proposal_id: str
    scenario_id: str
    annotator_ids: list[Literal["author_a", "author_b"]]
    status: Literal["draft", "complete"] = "draft"
    scheduling_acceptable: Literal["yes", "no"] | None = None
    autonomy_decision: Literal["act", "defer"] | None = None
    primary_reason: str = ""
    additional_reasons: list[str] = Field(default_factory=list)
    justification: str = ""
    disagreements: list[str] = Field(default_factory=list)
    adjudicated_by: str = ""
    original_review_sha256: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def complete_fields(self):
        if self.status == "complete":
            if set(self.annotator_ids) != set(AUTHORS) or not self.adjudicated_by.strip():
                raise ValueError("consensus requires both authors and named adjudicator")
            if set(self.original_review_sha256) != set(AUTHORS):
                raise ValueError("original review provenance missing")
            ProposalReview(proposal_id=self.proposal_id, scenario_id=self.scenario_id,
                           annotator_id="author_a", status="complete",
                           scheduling_acceptable=self.scheduling_acceptable,
                           autonomy_decision=self.autonomy_decision,
                           primary_reason=self.primary_reason,
                           additional_reasons=self.additional_reasons,
                           justification=self.justification)
        return self


def _path(root: Path, author: str, proposal_id: str) -> Path:
    if author not in AUTHORS:
        raise ValueError("unknown author")
    return root / "data" / "annotations" / author / f"{proposal_id}.json"


def _consensus_path(root: Path, proposal_id: str) -> Path:
    return root / "data" / "annotations" / "adjudicated" / f"{proposal_id}.json"


def _source(root: Path, proposal_id: str) -> dict:
    return next((row for row in catalog(root) if row["proposal_id"] == proposal_id), None) or (
        _raise("proposal not found"))


def _resolved_source(root: Path, proposal_id: str, source: dict | None) -> dict:
    """Use an already validated catalogue row when the caller has one.

    Streamlit renders the complete reviewer progress table on every interaction.  Rebuilding
    the proposal catalogue for every row made a single widget click perform dozens of full
    run/scenario scans.  Callers may pass the row from that same catalogue scan; the identity
    check below retains the provenance guard.
    """
    resolved = source if source is not None else _source(root, proposal_id)
    if resolved.get("proposal_id") != proposal_id or not resolved.get("scenario_id"):
        raise ValueError("proposal source provenance mismatch")
    return resolved


def _raise(message: str):
    raise ValueError(message)


def prepare(root: Path, author: str, proposal_ids: set[str] | None = None) -> int:
    if author not in AUTHORS:
        raise ValueError("unknown author")
    count = 0
    for source in catalog(root):
        if proposal_ids is not None and source["proposal_id"] not in proposal_ids:
            continue
        path = _path(root, author, source["proposal_id"])
        if path.exists():
            continue
        blank = ProposalReview(proposal_id=source["proposal_id"],
                               scenario_id=source["scenario_id"], annotator_id=author)
        atomic_json(path, blank.model_dump())
        count += 1
    return count


def load_review(root: Path, author: str, proposal_id: str, *,
                source: dict | None = None) -> tuple[ProposalReview, str]:
    source = _resolved_source(root, proposal_id, source)
    path = _path(root, author, proposal_id)
    if not path.exists():
        blank = ProposalReview(proposal_id=proposal_id,
                               scenario_id=source["scenario_id"], annotator_id=author)
        atomic_json(path, blank.model_dump())
    raw = path.read_bytes()
    review = ProposalReview.model_validate_json(raw)
    if (review.proposal_id, review.scenario_id, review.annotator_id) != (
            proposal_id, source["scenario_id"], author):
        raise ValueError("review provenance mismatch")
    return review, hashlib.sha256(raw).hexdigest()


def save_review(root: Path, author: str, proposal_id: str, data: dict,
                revision: str, *, confirm_completed: bool = False,
                source: dict | None = None) -> str:
    source = _resolved_source(root, proposal_id, source)
    old, current = load_review(root, author, proposal_id, source=source)
    if current != revision:
        raise ValueError("review changed elsewhere; reload before saving")
    if _consensus_path(root, proposal_id).exists():
        consensus = ProposalConsensus.model_validate_json(_consensus_path(root, proposal_id).read_text())
        if consensus.status == "complete":
            raise ValueError("review is frozen after completed adjudication")
    review = ProposalReview.model_validate(data)
    if (review.status == "complete" and not source["technical_validation"]["valid"]
            and review.scheduling_acceptable != "no"):
        raise ValueError("technically invalid proposal requires a quality rejection, not an autonomy label")
    if (review.proposal_id, review.scenario_id, review.annotator_id) != (
            old.proposal_id, old.scenario_id, author):
        raise ValueError("review ownership mismatch")
    if old.status == "complete" and old != review and not confirm_completed:
        raise ValueError("changing a completed review requires confirmation")
    if old != review:
        atomic_json(_path(root, author, proposal_id), review.model_dump())
    return hashlib.sha256(_path(root, author, proposal_id).read_bytes()).hexdigest()


def pair(root: Path, proposal_id: str) -> tuple[ProposalReview, ProposalReview, dict[str, str]]:
    reviews = [load_review(root, author, proposal_id) for author in AUTHORS]
    if any(review.status != "complete" for review, _ in reviews):
        raise ValueError("both independent reviews must be complete")
    return reviews[0][0], reviews[1][0], {author: reviews[i][1] for i, author in enumerate(AUTHORS)}


def compare(root: Path) -> dict:
    pairs, disagreements, decision_pairs = [], {}, []
    for source in catalog(root):
        pid = source["proposal_id"]
        try:
            a, b, _ = pair(root, pid)
        except (ValueError, OSError):
            continue
        pairs.append(pid)
        differences = [field for field in ("scheduling_acceptable", "autonomy_decision", "primary_reason")
                       if getattr(a, field) != getattr(b, field)]
        if differences:
            disagreements[pid] = differences
        if a.autonomy_decision and b.autonomy_decision:
            decision_pairs.append((a.autonomy_decision, b.autonomy_decision))
    agreement = (sum(a == b for a, b in decision_pairs) / len(decision_pairs)
                 if decision_pairs else None)
    return {"complete_pairs": pairs, "disagreements": disagreements,
            "observed_autonomy_agreement": agreement, "cohens_kappa": cohens_kappa(decision_pairs)}


def load_consensus(root: Path, proposal_id: str) -> ProposalConsensus:
    a, b, hashes = pair(root, proposal_id)
    path = _consensus_path(root, proposal_id)
    if path.exists():
        return ProposalConsensus.model_validate_json(path.read_text())
    differences = [field for field in ("scheduling_acceptable", "autonomy_decision", "primary_reason")
                   if getattr(a, field) != getattr(b, field)]
    return ProposalConsensus(proposal_id=proposal_id, scenario_id=a.scenario_id,
                             annotator_ids=list(AUTHORS), disagreements=differences,
                             original_review_sha256=hashes)


def save_consensus(root: Path, proposal_id: str, data: dict,
                   *, confirm_completed: bool = False) -> None:
    a, b, hashes = pair(root, proposal_id)
    new = ProposalConsensus.model_validate(data)
    if (new.status == "complete" and not _source(root, proposal_id)["technical_validation"]["valid"]
            and new.scheduling_acceptable != "no"):
        raise ValueError("technically invalid proposal cannot receive an autonomy consensus")
    if (new.proposal_id, new.scenario_id) != (proposal_id, a.scenario_id):
        raise ValueError("consensus provenance mismatch")
    if new.original_review_sha256 != hashes:
        raise ValueError("original reviews changed; reload consensus")
    actual_disagreements = {field for field in ("scheduling_acceptable", "autonomy_decision", "primary_reason")
                            if getattr(a, field) != getattr(b, field)}
    if not actual_disagreements <= set(new.disagreements):
        raise ValueError("consensus must record all observed disagreement fields")
    path = _consensus_path(root, proposal_id)
    if path.exists():
        old = ProposalConsensus.model_validate_json(path.read_text())
        if old.status == "complete" and old != new and not confirm_completed:
            raise ValueError("changing completed consensus requires confirmation")
    atomic_json(path, new.model_dump())
