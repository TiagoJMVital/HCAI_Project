# Two-stage annotation protocol

This document explains the workflow implemented in `src/annotation_workflow.py` and specified in [ANNOTATION.md](../ANNOTATION.md). The **scenario** annotation records context and acceptable outcomes; the **proposal** annotation assigns `act/defer` to a particular final B proposal. Two authors work independently, then explicitly adjudicate disagreements. No human forms are complete at present.

## Stage 1: scenario context

Run `python src/annotation_workflow.py prepare-scenarios author_a` and repeat for `author_b`. Each author receives `data/annotation_work/<author>/scenario/packets/<scenario_id>.json` (request, simulated time, synthetic calendar and preference profile) and a separate blank `forms/<scenario_id>.json`. Packets exclude family, split, preliminary label, model outputs and the other author's answers. The form requires relevant `hard_constraints`, one or more `acceptable_outcomes` (allow multiple acceptable schedules), `impact_factors`, `ambiguity_present` and, when true, `ambiguity_notes`. It does **not** ask for `act/defer`.

Set `status` to `complete` only when a form is finished. After both authors finish, run:

```bash
python src/annotation_workflow.py compare scenario author_a author_b
python src/annotation_workflow.py prepare-adjudications scenario author_a author_b
```

The comparison highlights literal differences; it cannot decide semantic equivalence. The authors discuss and fill `data/annotation_work/adjudications/scenario/<scenario_id>.json`, including a `resolution_rationale`, both `resolved_by` IDs and `status="complete"`; then run `validate-adjudications scenario author_a author_b`. No answer is copied automatically.

## Generating proposal material

Configuration B is the source. Its result records all iterations and model metadata. After deciding a limited collection plan, run a **single** synthetic B scenario as needed and import the JSON result:

```bash
python eval/run_config_b.py --only soft_gym_01 --experiment-id annotation-pilot --repeat-index 0
python src/proposal_catalog.py eval/runs/<run_id>/B/soft_gym_01.json
```

The runner makes IAedu calls if IAedu is configured; these commands are instructions, not part of this documentation-only phase. The importer accepts only B results with `status=proposal_ready` and `critic_accepted=true`. It assigns a stable `proposal_id`, links it to scenario/base/family/split/run/configuration/model, and preserves full refinement history and score in `data/proposal_sources/`. That provenance store is **not** an annotator packet. Proposals below the Critic threshold never reach the intended gate and are outside its training input distribution. The existing repository has one imported B proposal from `soft_gym_01`; it has not been human-labelled.

## Stage 2: concrete proposal

Only after the corresponding scenario is independently annotated and adjudicated, run `prepare-proposals author_a` and `prepare-proposals author_b`. The packet shows the original scenario, adjudicated scenario reference, **final** proposed changes and their rationale. It hides fixed-rule decisions, `draft_label`, Critic score/feedback, revision history, model, split and other configurations. An annotator should not open `eval/runs/` or `data/proposal_sources/` before locking their form. Local filesystem separation is procedural, not a technical access barrier.

In `proposal/forms/<proposal_id>.json`, each author records `decision` (`act` or `defer`), `decision_rationale`, `scheduling_acceptable`, `intervention_impact` (1–5), `intervention_risk` (1–5), `risk_factors` and any `ambiguity_notes`. `act` requires `scheduling_acceptable=true`. A structurally impossible proposal should be flagged as unacceptable and corrected/rejected; if a form must be completed for analysis, `defer` means **do not act**, not that the proposal becomes valid after confirmation. The authors should record this distinction explicitly in the rationale. A valid proposal may still require confirmation because of impact, ambiguity or third parties.

After both forms are complete, run `compare proposal author_a author_b`, then `prepare-adjudications proposal author_a author_b`. The comparison computes observed agreement and Cohen's kappa for paired `act/defer` decisions when defined, and reports differences in acceptability/impact/risk. Kappa is undefined with no pairs or expected agreement of 1, and is unstable on a tiny pilot. The authors manually fill `adjudications/proposal/<proposal_id>.json` with final decision, reasons, impact/risk, acceptable status, both `resolved_by` IDs and `status="complete"`; run `validate-adjudications proposal author_a author_b`.

## Gate dataset, grouping and blindness

After complete training-family annotations and adjudications, `python src/gate_dataset.py --split train` writes `data/gate_datasets/train.jsonl`. Each row links provenance metadata (`scenario_id`, `proposal_id`, base, family, split, run and model), Critic score, a predictive `features` object and the **adjudicated proposal label**. Predictors currently include score, change type/count, touched-event importance, heuristic conflict/impact and sensitive-category contact. IDs, family, split and human ratings are excluded from predictors. Feature definitions are heuristics and require review/freeze before looking at held-out labels. Test export requires `--split test --unlock-test` after model and settings are frozen. Grouped folds keep all proposals of a base/family together. `src/gate_dataset.py` exports data; it does not train a classifier.

## Clearly illustrative form examples

These are **hypothetical examples only**, not annotations of repository scenarios or author labels:

- Scenario example: “A class from 10:00–12:00 is fixed; acceptable outcomes are any 60-minute study block after class and before the stated deadline; the request leaves the exact afternoon slot open.” This belongs in `hard_constraints`, `acceptable_outcomes` and `ambiguity_notes`, with **no** autonomy label.
- Proposal example: “Move an explicitly movable solo gym session to an unoccupied evening slot while preserving its duration; `scheduling_acceptable=true`, impact 2/5, risk 1/5; hypothetical `act` because the user explicitly allowed that move.” The scores and label are illustrations for discussion, not data.
- Contrasting proposal example for the **same kind of request**: “Delete a paid group class involving another person; `scheduling_acceptable` may be true for the time objective, but hypothetical `defer` because of cost and third-party effect.” Again this is a policy hypothesis, never a benchmark label.

## Small annotation pilot before formal collection

Use **training-family** cases only: `hard_class_01`, `hard_exam_02`, `soft_gym_01`, `gym_importance_02`, `amb_health_01` and `health_specificity_02` (verify exact scenario details in JSON before choosing the final six). One accepted final B proposal already exists for `soft_gym_01`; further proposal material would require later, separately planned synthetic B runs. Do not create fake proposals or call the API merely to fill the pilot. If fewer accepted proposals are available, begin scenario annotation for all six and proposal annotation only for available concrete proposals.

Both authors first read the [policy draft](08_AUTONOMY_POLICY_DRAFT.md), annotate independently, lock forms, compare, and discuss ambiguous criteria and disagreements. Record changes to definitions and examples in a dated protocol note, then rerun a small development-only check if needed. **Freeze the policy before formal annotation.** Do not move or edit held-out test families based on pilot outcomes; do not treat pilot agreement as a performance result.
