# Roadmap and decision log

This is a status map, not evidence that the scientific hypotheses have been confirmed. The source of requirements is the [Project Proposal](../../HCAI_Project_Proposal.pdf), especially §§3–5. The [traceability table](01_PROJECT_OVERVIEW.md#proposal-traceability) relates those requirements to code, tests and next actions.

## Completed as software, subject to stated limits

| Work | Evidence | Limit |
| --- | --- | --- |
| Shared Pydantic scenario, proposal and Critic contracts | `src/models.py`; local tests | Structural typing does not prove semantic scheduling quality. |
| IAedu structured-generation provider and selectable Ollama alternative | `src/llm.py`, `tests/test_llm.py` | Mock tests and isolated live checks; no API availability guarantee. |
| A runner with fixed-rule autonomy | `eval/run_config_a.py`, `src/rules.py` | Synthetic, simulated action only. |
| B Critic and bounded refinement | `src/critic.py`, `src/pipeline_b.py`, `eval/run_config_b.py` | One recorded synthetic live scenario; no aggregate evidence. |
| Synthetic benchmark and family split | `src/make_benchmark.py`, `src/benchmark.py`, 41 JSON scenarios | Three training families only; private-calendar part of proposal absent. |
| Two-stage annotation and gate-data preparation tools | `src/annotation_workflow.py`, `src/proposal_catalog.py`, `src/gate_dataset.py` | No completed human adjudications, no gate dataset export. |

## Partially complete

- **Operational safety:** `find_violations` catches several concrete failures, but does not model every hard/soft constraint, third-party consequence or full request meaning. Extend and test before claiming safe automation.
- **Scheduling quality:** `data/objective_checks.json` covers only five requests with partial machine-checkable conditions. Human acceptable-outcome assessment is still needed.
- **Experimental records:** A/B runners capture run/model/proposal/decision/duration and B iterations; an offline pairer exists. Repeated, controlled comparisons and independent human scoring have not happened.
- **Autonomy policy:** fixed rules exist as a baseline; the [discussion draft](08_AUTONOMY_POLICY_DRAFT.md) is not a human-adjudicated policy.

## Recommended sequence and dependencies

| Priority / phase | Concrete work | Depends on | Completion criterion |
| --- | --- | --- | --- |
| 1. Policy and pilot | Both authors review policy draft; annotate 5–6 **training** scenario packets and available concrete proposals independently; discuss discrepancies; freeze form instructions | Current benchmark and annotation tools | Written, dated protocol decision; completed pilot forms and disagreement notes; test families unchanged |
| 2. Formal training references | Predeclare collection frequency; collect accepted B proposals across training families; complete two-author scenario/proposal annotations and adjudications | Phase 1 | Every selected training proposal has both independent forms and adjudicated label; agreement reported with limits |
| 3. Quality evaluation | Add defensible objective checks; define human scheduling/rationale rubric and blind assessment process; audit validator coverage | Phase 1; can partly run in parallel with phase 2 | Checks/rubric frozen; invalid, unknown and acceptable cases separated in evaluation output |
| 4. Gate design freeze | Review proposed features for leakage/availability, grouped folds and class diversity **on training data**; predeclare classifier, threshold and metrics | Phases 1–2 | Feature and analysis specification fixed before test labels are inspected |
| 5. Configuration C | Train on training-family proposal rows; integrate gate after B acceptance while preserving deterministic safety; test fallback on errors | Phase 4 | C runs on synthetic cases, with matched B proposal path, reproducible model artifact and passing safety tests |
| 6. Controlled evaluation | Repeated A/B/C runs using frozen settings; score scheduling, rationale and autonomy separately; finally unlock held-out family labels | Phases 3–5 | Complete run ledger, all failures retained, uncertainty and family-level results reported without test tuning |
| 7. Deliverable scope | Decide whether and how n8n/Google Calendar/private calendar data are required; implement only with privacy and authorization plan | Author and course decision | Explicit scope decision and, if required, safe integration tests |

Do not use held-out labels to rewrite fixed autonomy rules, tune features, choose a gate model or select showcase examples. If more data are needed after a test-set audit, version the benchmark and report that separately.

## Questions for both authors

1. What exact boundary separates an invalid proposal to correct/reject from a valid proposal requiring confirmation? Should formal proposal forms add an explicit invalidity field, given the current `scheduling_acceptable` field and `act/defer` contract?
2. What impact/risk scale anchors and third-party rules should the annotation handbook use? How should repeated borderline cases be resolved consistently?
3. How many proposals per training scenario, how many A/B/C repetitions and what sampling/stop rule are feasible under IAedu quota? Freeze these before collection.
4. Should A proposals also be independently annotated for a direct A/B autonomy analysis? The current gate catalog intentionally imports accepted B proposals only.
5. Is a Python-only orchestration and synthetic-calendar demonstrator sufficient for the course, or must n8n and Google Calendar from the proposal be delivered? If private calendars are used, what consent, minimization and storage rules apply?
6. What human rationale rubric and uncertainty-reporting method will be adopted before viewing outputs? What constitutes a meaningful improvement beyond Critic self-scoring?

These are methodological decisions, not settings to infer from existing preliminary labels.
