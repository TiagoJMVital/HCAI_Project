# Human-Centered AI calendar assistant

This research prototype compares **A** (Proposer and fixed autonomy rules), **B** (the same Proposer, an independent Critic with up to three revisions, then the same rules), and **C** (a learned Learning-to-Defer gate). The current C artefact is a deterministic logistic model trained on eligible training-family proposals with grouped out-of-fold diagnostics; it has not been evaluated on the locked test split. All calendars are synthetic and `act` is a simulated decision; there is no Google Calendar write integration.

In B, the Critic evaluates the structured operations, the Proposer's rationale, and the **complete calendar resulting from deterministic in-memory simulation**, plus the limited technical validation report. It receives the calendar timezone but no separate original request, full profile, original calendar or human labels. It distinguishes objective contradictions, evidence-backed plausibility risks and subjective improvements; consecutive events are not automatically invalid. A remains unchanged. The four scoring dimensions and the 4.0 threshold/three-revision limit are unchanged. See [Architecture](docs/02_ARCHITECTURE.md).

**Critic policy `uncertainty_review_v2`:** New B responses contain the validated `plausibility_review` decision and a required list of `unresolved_assumptions`. An empty list means none identified in that evaluation; absence in a historical run means the question was not assessed. B accepts only when the existing numeric criteria pass **and** the Critic explicitly says no plausibility revision is required. An uncertainty can remain recorded in an accepted proposal. It neither triggers a fixed ACT/DEFER rule nor proves external feasibility. Earlier `plausibility_review_v1` results remain readable.

The Critic prompt now explicitly asks whether an unresolved condition has been **meaningfully reconsidered** and whether another review could improve or better justify the plan. Recording a condition does not answer that question; proof of objective impossibility is not required to request review. A material uncertainty can still remain after an accepted review when another iteration would add little value. Prompt SHA-256 values identify runs before and after this guidance change.

The Critic's primary review lens is now the **human sustainability of the resulting routine**: cumulative effort, everyday needs, rest, useful time and proportional trade-offs across the visible horizon. `reasoning` and `coherence` explicitly assess practical manageability, while the deterministic validator remains responsible for computable hard constraints. The Critic raises questions for the Proposer rather than choosing replacement times. A shorter, reorganized prompt replaces repeated technical-versus-plausibility cautions; no score, threshold, response field or fixed autonomy rule changed. The revision-only Proposer guidance asks for a whole-plan reassessment rather than a cosmetic time shift.

The Critic now acts as a **quality-control reviewer**: a concrete, relevant practical doubt can trigger re-evaluation without a hard-constraint violation. Minor or speculative observations do not. The Proposer can change the calendar **or keep identical operations with a grounded response**; the Critic receives its previous concern on the next iteration. This adds no universal transition, meal or rest rules. Run prompt hashes distinguish this guidance from earlier B executions.

On a revised proposal, the Critic examines **both** whether the earlier concern was addressed and whether the new calendar creates other risks. It receives the previous simulated calendar for that comparison. Unknown opening hours, travel and third-party availability can be recorded as structured uncertainty, never invented as technical constraints. The Proposer now receives the same explicit flexibility-versus-feasibility guidance in A and B; this changes its base prompt hash for **both** configurations, so compare experimental versions separately. The uncertainty list is retained in runs and imported proposal artifacts but is **not** exported as a gate feature by the current exporter. See [Architecture](docs/02_ARCHITECTURE.md).

## Official workflow

1. Create a standalone `schema_version: "2.0"` scenario using [`working_student_deadline_001.json`](data/scenarios/working_student_deadline_001.json) as the checked-in contract example. Keep profile, calendar, reference time and request in the scenario; do not add labels or expected solutions. See [benchmark specification](docs/03_BENCHMARK.md).
2. Validate and import it. Assign the entire family to `train` or `test` **before** importing. The active corpus lives in `data/scenarios/`, and the split manifest is `data/benchmark_manifest.json`.
3. Explicitly run configuration B to generate a proposal, then import its result into `data/proposals/`. Generation invokes the configured LLM and is never triggered by opening Streamlit. Configuration A is available as the paired baseline.
4. The preferred protocol remains two independent reviews plus adjudication. The current time-bounded training pass instead records the split-author labels transparently as `joint_consensus`, linked by SHA-256 to the sole completed source review; these labels must not be used to claim inter-rater agreement.
5. Export eligible labels to `data/gate_datasets/`, then train C. The test split remains locked until the model and evaluation policy are frozen.

```bash
source .venv/bin/activate
python src/benchmark_v2.py validate data/scenarios/working_student_deadline_001.json
python src/benchmark_v2.py import /path/to/new_scenario.json --split train
python src/benchmark_v2.py validate
# Explicit LLM calls; run only when authorised and configured:
python eval/run_config_b_v2.py --only working_student_deadline_001
# Optional fixed initial proposal: skips the first Proposer call; the Critic still runs.
python eval/run_config_b_v2.py --only <scenario_id> --initial-proposal-from eval/runs/treino/<family>/<scenario_id>/<run_id>/B/<scenario_id>.json
# Import the printed B result path without another LLM call:
python src/proposal_catalog_v2.py eval/runs/treino/<family>/<scenario_id>/<run_id>/B/<scenario_id>.json
# Or idempotently import all eligible canonical training B results:
python src/proposal_catalog_v2.py --training
streamlit run annotation_app.py --server.address 127.0.0.1
# Preferred independent-adjudication export:
python src/gate_dataset_v2.py --split train
# Explicit non-independent protocol used by the current training artefact:
python src/joint_consensus_v2.py --adjudicated-by author_a_and_author_b
python src/gate_dataset_v2.py --split train --label-protocol joint_consensus
python src/train_gate_v2.py
```

New results use `eval/runs/treino/<family>/<scenario_id>/<run_id>/A|B/<scenario_id>.json` for training, `eval/runs/avaliacao/desenvolvimento/...` for development and `eval/runs/avaliacao/teste/...` for test. Discovery and replay remain compatible with historical layouts. The final training batch is sequential and resumable: `python eval/run_training_b_v2.py --resume`; inspect its selection without provider calls with `python eval/run_training_b_v2.py --dry-run --resume`. A technically completed result is imported into the annotation catalogue immediately. Completion is verified from the proposal, validation, calendar and Critic history rather than trusting the top-level status. The source hash and the same integrity contract protect annotation loading and gate export. A failed import is preserved but quarantined; existing annotations are never rewritten. The resume scan skips only integrity-verified terminal B results and leaves pending or technically failed scenarios eligible for a later bounded retry. Failed attempts remain outside active `eval/runs/`, with raw model output and sanitized diagnostics archived under `eval/technical_failures/`. Never re-import the included example scenario, which is already in `data/scenarios/`.

`--initial-proposal-from` accepts a prior schema-2 B run JSON. It checks scenario identity and deterministic applicability, reuses its **first** proposal exactly, and stores source run/proposal and current scenario SHA-256 hashes in a new run. Only a Critic-requested revision calls the Proposer. It does not replay the old Critic response or overwrite the source. The current Critic prompt is used. See [experimental design](docs/05_EXPERIMENTAL_DESIGN.md) for comparability limits.

## Local annotation

Start Streamlit from the project directory, then open the URL it prints, usually `http://localhost:8501`. The author selector separates local work; it is **not authentication**. In **Propostas**, select a profile family and scenario, inspect the complete request, synchronized original/proposed calendars, structured changes and complete constraints, save an incomplete draft, then complete the review. Family and overall progress are reviewer-specific. Run IDs, Critic judgments, rule-based autonomy decisions and the other reviewer's answers are hidden from this independent-review page; diagnostic and adjudication views retain the underlying information. Comparison and adjudication are shown only after both authors finish. An unacceptable or technically invalid proposal is a quality rejection without an `act/defer` label. The weekly view marks temporal overlaps, which alone do not prove a hard-constraint violation.

## Verify without LLM calls

```bash
python src/benchmark_v2.py validate
python -m pytest -q
```

The active repository combines local contract examples with the authoritative final 100-scenario manifest and its imported training B proposals. Training, development and test membership is read from structured manifest metadata, never scenario-ID prefixes. Historical results and annotations remain preserved; no preliminary label or old annotation becomes ground truth automatically.

**Final 100-scenario dataset:** [`scenarios/`](scenarios/) is part of this repository and contains the 100 strict schema `2.0` scenarios, the grouped 60/10/30 train/dev/test manifest, duration sidecars and exact confirmed-change sidecars. The archival `../Cenarios_v2_100_final.zip`, when present, contains the same dataset but is not required to run a fresh clone. See the [central scenario audit](docs/scenario_audit.md), [status per scenario](docs/scenario_final_status.csv), [final decisions](docs/scenario_final_decisions.md), and [pilot plan](docs/pilot_plan.md). Sidecars are versioned separately and bound to scenario content by SHA-256. Duration checks certify scheduled time, not completed work. Exact change exceptions authorize only the named event and operation. Proposals with no operations are structurally permitted but do not prove request satisfaction; the current gate exporter excludes them pending an eligibility decision. The `dev` split is distinct from `train` and is never included in grouped training folds.

## Documentation

| Document | Purpose |
| --- | --- |
| [Project overview](docs/01_PROJECT_OVERVIEW.md) | Research aim and current state |
| [Architecture](docs/02_ARCHITECTURE.md) | Components, A/B flows and safety |
| [Benchmark](docs/03_BENCHMARK.md) | Schema 2.0, family split and import |
| [Annotation protocol](docs/04_ANNOTATION_PROTOCOL.md) | Independent reviews and consensus |
| [Experimental design](docs/05_EXPERIMENTAL_DESIGN.md) | A/B/C comparison and evidence limits |
| [Setup and testing](docs/06_SETUP_AND_TESTING.md) | WSL2 and local checks |
| [Roadmap](docs/07_ROADMAP.md) | Remaining scientific work |
| [Autonomy policy draft](docs/08_AUTONOMY_POLICY_DRAFT.md) | Discussion aid, not labels |
| [Cleanup record](docs/09_CLEANUP_PLAN.md) | Data preservation and migration |
