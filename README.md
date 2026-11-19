# Human-Centered AI calendar assistant

This research prototype compares **A** (Proposer and fixed autonomy rules), **B** (the same Proposer, an independent Critic with up to three revisions, then the same rules), and the planned **C** (a learned Learning-to-Defer gate). All calendars are synthetic and `act` is a simulated decision; there is no Google Calendar write integration or trained gate.

In B, the Critic evaluates the structured operations, the Proposer's rationale, and the **complete calendar resulting from deterministic in-memory simulation**, plus the limited technical validation report. It receives the calendar timezone but no separate original request, full profile, original calendar or human labels. It distinguishes objective contradictions, evidence-backed plausibility risks and subjective improvements; consecutive events are not automatically invalid. A remains unchanged. The four scoring dimensions and the 4.0 threshold/three-revision limit are unchanged. See [Architecture](docs/02_ARCHITECTURE.md).

**Critic policy `uncertainty_review_v2`:** New B responses contain the validated `plausibility_review` decision and a required list of `unresolved_assumptions`. An empty list means none identified in that evaluation; absence in a historical run means the question was not assessed. B accepts only when the existing numeric criteria pass **and** the Critic explicitly says no plausibility revision is required. An uncertainty can remain recorded in an accepted proposal. It neither triggers a fixed ACT/DEFER rule nor proves external feasibility. Earlier `plausibility_review_v1` results remain readable.

The Critic prompt now explicitly asks whether an unresolved condition has been **meaningfully reconsidered** and whether another review could improve or better justify the plan. Recording a condition does not answer that question; proof of objective impossibility is not required to request review. A material uncertainty can still remain after an accepted review when another iteration would add little value. Prompt SHA-256 values identify runs before and after this guidance change.

The Critic's primary review lens is now the **human sustainability of the resulting routine**: cumulative effort, everyday needs, rest, useful time and proportional trade-offs across the visible horizon. `reasoning` and `coherence` explicitly assess practical manageability, while the deterministic validator remains responsible for computable hard constraints. The Critic raises questions for the Proposer rather than choosing replacement times. A shorter, reorganized prompt replaces repeated technical-versus-plausibility cautions; no score, threshold, response field or fixed autonomy rule changed. The revision-only Proposer guidance asks for a whole-plan reassessment rather than a cosmetic time shift.

The Critic now acts as a **quality-control reviewer**: a concrete, relevant practical doubt can trigger re-evaluation without a hard-constraint violation. Minor or speculative observations do not. The Proposer can change the calendar **or keep identical operations with a grounded response**; the Critic receives its previous concern on the next iteration. This adds no universal transition, meal or rest rules. Run prompt hashes distinguish this guidance from earlier B executions.

On a revised proposal, the Critic examines **both** whether the earlier concern was addressed and whether the new calendar creates other risks. It receives the previous simulated calendar for that comparison. Unknown opening hours, travel and third-party availability can be recorded as structured uncertainty, never invented as technical constraints. The Proposer now receives the same explicit flexibility-versus-feasibility guidance in A and B; this changes its base prompt hash for **both** configurations, so compare experimental versions separately. The uncertainty list is retained in runs and imported proposal artifacts but is **not** exported as a gate feature by the current exporter. See [Architecture](docs/02_ARCHITECTURE.md).

## Official workflow

1. Create a standalone `schema_version: "2.0"` scenario from [`scenario_v2_example.json`](../scenario_v2_example.json). Keep profile, calendar, reference time and request in the scenario; do not add labels or expected solutions. See [benchmark specification](docs/03_BENCHMARK.md).
2. Validate and import it. Assign the entire family to `train` or `test` **before** importing. The active corpus lives in `data/scenarios/`, and the split manifest is `data/benchmark_manifest.json`.
3. Explicitly run configuration B to generate a proposal, then import its result into `data/proposals/`. Generation invokes the configured LLM and is never triggered by opening Streamlit. Configuration A is available as the paired baseline.
4. Two authors independently review the same imported proposal in Streamlit. Reviews and consensus live in `data/annotations/author_a/`, `author_b/`, and `adjudicated/`.
5. Export eligible, adjudicated training examples to `data/gate_datasets/`. The test split remains locked until the model and evaluation policy are frozen.

```bash
source .venv/bin/activate
python src/benchmark_v2.py validate ../scenario_v2_example.json
python src/benchmark_v2.py import /path/to/new_scenario.json --split train
python src/benchmark_v2.py validate
# Explicit LLM calls; run only when authorised and configured:
python eval/run_config_b_v2.py --only working_student_deadline_001
# Optional fixed initial proposal: skips the first Proposer call; the Critic still runs.
python eval/run_config_b_v2.py --only working_student_deadline_001 --initial-proposal-from eval/runs/e9052e6757c14820a06b89ddaf9aafe6/B/working_student_deadline_001.json
# Import the printed B result path without another LLM call:
python src/proposal_catalog_v2.py eval/runs/<run_id>/B/working_student_deadline_001.json
streamlit run annotation_app.py --server.address 127.0.0.1
python src/gate_dataset_v2.py --split train
```

An existing historical B result is under `eval/runs/<run_id>/B_v2/`; its imported proposal is already in `data/proposals/`. Never re-import the included example scenario, which is already in `data/scenarios/`. A's matching command is `python eval/run_config_a_v2.py --only <scenario_id>`. Both runners can select provider and model through CLI options or `.env`. For detailed instructions, see [ANNOTATION.md](ANNOTATION.md) and [setup and testing](docs/06_SETUP_AND_TESTING.md).

`--initial-proposal-from` accepts a prior schema-2 B run JSON. It checks scenario identity and deterministic applicability, reuses its **first** proposal exactly, and stores source run/proposal and current scenario SHA-256 hashes in a new run. Only a Critic-requested revision calls the Proposer. It does not replay the old Critic response or overwrite the source. The current Critic prompt is used. See [experimental design](docs/05_EXPERIMENTAL_DESIGN.md) for comparability limits.

## Local annotation

Start Streamlit from the project directory, then open the URL it prints, usually `http://localhost:8501`, in the Windows browser. The author selector separates local work; it is **not authentication**. Select a proposal, inspect the original and proposed read-only weekly calendars, technical validation and Critic history, save an incomplete draft, then complete the review. Comparison and adjudication are shown only after both authors finish. An unacceptable or technically invalid proposal is a quality rejection without an `act/defer` label. The weekly view marks temporal overlaps, which alone do not prove a hard-constraint violation.

## Verify without LLM calls

```bash
python src/benchmark_v2.py validate
python -m pytest -q
```

The active corpus currently contains **one** imported v2 scenario, imported B proposals and author drafts. The previous 20-base/41-variant benchmark, old annotations and historical results are preserved in the local SHA-256-verified archive described in [archive/README.md](archive/README.md); they are not part of the active corpus. The archive folders are ignored by Git to avoid committing duplicate files. Historical committed revisions remain accessible through Git history. No preliminary labels or old annotations become ground truth automatically.

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
