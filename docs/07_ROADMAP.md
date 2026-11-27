# Roadmap

## Completed engineering work

- Schema `2.0` standalone scenario validation/import with family split checks (`src/scenario_v2.py`, `src/benchmark_v2.py`).
- Shared structured Proposer/Critic contracts, IAedu and Ollama providers, deterministic calendar simulation, fixed-rule A/B decisions, Critic refinement loop and unique runs (`src/`, `eval/`).
- Direct proposal catalog, Streamlit before/after weekly calendar, independent author forms, comparison/adjudication and gate dataset export (`src/proposal_catalog_v2.py`, `annotation_app.py`, `src/annotation_v2.py`, `src/gate_dataset_v2.py`).
- Explicit hash-bound joint-consensus fallback and deterministic logistic C trainer with grouped training-family diagnostics (`src/joint_consensus_v2.py`, `src/train_gate_v2.py`).
- Preservation of prior 41-scenario corpus, old annotations and results in a verified local archive. The active benchmark holds one v2 scenario/proposal and one author draft.

## Pending scientific work, in dependency order

1. **Benchmark expansion (high):** create diverse independent schema `2.0` cases across profiles and families, freeze train/test assignment, validate all inputs. Completion: documented scenario coverage and no family split leakage.
2. **Annotation policy and pilot (medium):** agree on quality/autonomy rubrics, whether Critic metadata stays visible, and review a small training-family sample independently. Completion: both authors can apply the protocol consistently; disagreements and changes are recorded without touching test families.
3. **Paired A/B study (high):** freeze provider settings, generate repeated paired outputs, import final B proposals, evaluate scheduling and rationale separately. Completion: reproducible run manifest, independent quality assessment and uncertainty reporting.
4. **Formal proposal review (high):** two author reviews plus adjudication for eligible B proposals. Completion: valid consensus with traceable original forms and class-diverse training labels without fabricated examples.
5. **Configuration C evaluation (high):** review and freeze the current feature and threshold policy, replace joint labels with independent adjudication where feasible, then unlock and evaluate once on held-out families. Completion: calibrated Act/Defer test results, safety/error analysis and A/B/C comparison. Current grouped training diagnostics are provisional, not completion evidence.

External calendar writes, n8n automation and conversational clarification are not in the current implementation. Decide their scope explicitly rather than treating them as already tested. Never use old generator pre-labels as human ground truth.
