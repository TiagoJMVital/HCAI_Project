# Human-Centered AI calendar assistant

This research prototype compares **A** (Proposer and fixed autonomy rules), **B** (the same Proposer, an independent Critic with up to three revisions, then the same rules), and the planned **C** (a learned Learning-to-Defer gate). All calendars are synthetic and `act` is a simulated decision; there is no Google Calendar write integration or trained gate.

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
# Import the printed B result path without another LLM call:
python src/proposal_catalog_v2.py eval/runs/<run_id>/B/working_student_deadline_001.json
streamlit run annotation_app.py --server.address 127.0.0.1
python src/gate_dataset_v2.py --split train
```

An existing historical B result is under `eval/runs/<run_id>/B_v2/`; its imported proposal is already in `data/proposals/`. Never re-import the included example scenario, which is already in `data/scenarios/`. A's matching command is `python eval/run_config_a_v2.py --only <scenario_id>`. Both runners can select provider and model through CLI options or `.env`. For detailed instructions, see [ANNOTATION.md](ANNOTATION.md) and [setup and testing](docs/06_SETUP_AND_TESTING.md).

## Local annotation

Start Streamlit from the project directory, then open the URL it prints, usually `http://localhost:8501`, in the Windows browser. The author selector separates local work; it is **not authentication**. Select a proposal, inspect the original and proposed read-only weekly calendars, technical validation and Critic history, save an incomplete draft, then complete the review. Comparison and adjudication are shown only after both authors finish. An unacceptable or technically invalid proposal is a quality rejection without an `act/defer` label. The weekly view marks temporal overlaps, which alone do not prove a hard-constraint violation.

## Verify without LLM calls

```bash
python src/benchmark_v2.py validate
python -m pytest -q
```

The active corpus currently contains **one** imported v2 scenario, one imported B proposal and one `author_a` draft. The previous 20-base/41-variant benchmark, old annotations and historical results are preserved in the local SHA-256-verified archive described in [archive/README.md](archive/README.md); they are not part of the active corpus. The archive folders are ignored by Git to avoid committing duplicate files. Historical committed revisions remain accessible through Git history. No preliminary labels or old annotations become ground truth automatically.

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
