# Human-Centered AI calendar assistant

This research prototype studies contextual calendar proposals, independent critique and calibrated autonomy. The [Project Proposal](../HCAI_Project_Proposal.pdf) defines three configurations: **A** (Proposer + fixed autonomy rules), **B** (the same Proposer + Critic/refinement + the same rules), and **C** (a future learned Learning-to-Defer gate). A and B currently run on synthetic calendars. All `act` decisions are simulated; no Google Calendar integration or configuration C exists.

## Start here

| Document | Read it for |
| --- | --- |
| [01 Project overview](docs/01_PROJECT_OVERVIEW.md) | Research aims, current evidence, proposal traceability and deviations |
| [02 Architecture](docs/02_ARCHITECTURE.md) | A/B flow, contracts, providers, validation and failure handling |
| [03 Benchmark](docs/03_BENCHMARK.md) | Legacy 20 bases/41 variants plus the new independent v2 scenario contract |
| [04 Annotation protocol](docs/04_ANNOTATION_PROTOCOL.md) | Direct proposal reviews, adjudication and v2 gate dataset |
| [05 Experimental design](docs/05_EXPERIMENTAL_DESIGN.md) | A/B/C comparison, metrics, repetitions and evidence boundaries |
| [06 Setup and testing](docs/06_SETUP_AND_TESTING.md) | WSL2 setup, safe IAedu configuration, exact commands and results |
| [07 Roadmap](docs/07_ROADMAP.md) | Completed and pending work, dependencies and author decisions |
| [08 Autonomy policy draft](docs/08_AUTONOMY_POLICY_DRAFT.md) | Discussion examples for proposal-level Act/Defer decisions |

The current [ANNOTATION.md](ANNOTATION.md) is the command reference for the **direct proposal workflow**. The former two-stage scenario/proposal annotation code and data remain available as a legacy archive; scenario annotation is no longer required. Both authors must still review proposals independently. Legacy `draft_label` values are preliminary generator metadata, **not** ground truth.

## Local annotation interface

The Streamlit interface edits author-specific JSON forms for direct v2 proposal reviews. After installing `requirements.txt` in the WSL2 virtual environment, start it from the repository root:

```bash
source .venv/bin/activate
streamlit run annotation_app.py --server.address 127.0.0.1
```

Open the local URL shown in the terminal (normally `http://localhost:8501`) in the Windows browser. Select `author_a` or `author_b`, open **Propostas v2**, and evaluate a final imported B proposal. Filter by profile, family and state; save drafts, conclude reviews, then use **Consenso v2** once both authors have finished. The author selector separates work locally; it is not authentication. The old UI pages remain under **Arquivo**. Starting this app does not call IAedu. See [ANNOTATION.md](ANNOTATION.md) for import, review, adjudication and export commands.

The review page begins with a **read-only weekly calendar** (Monday–Sunday, 24-hour times). Its week comes from the scenario, and a dashed amber band appears only when a narrow deterministic parser identifies a requested interval. Colored blocks also state **Fixo** or **Flexível**. The **Original / Proposto** toggle is available only after safe in-memory simulation; added, moved and removed blocks have distinct styles. Temporal overlap is not itself a hard-constraint violation. A preview never edits a real calendar or proves request satisfaction. The UI also shows the final rationale, technical-validation coverage and Critic scores/iterations. See [the protocol](docs/04_ANNOTATION_PROTOCOL.md) for interpretation limits.

## Quick local verification

From the WSL2 repository root, after following the environment steps in [Setup and testing](docs/06_SETUP_AND_TESTING.md):

```bash
python src/validate_data.py
python -m pytest -q tests
```

The current local suite verifies both the existing 41-scenario benchmark and the v2 workflow with mocked providers; run the commands above for the current counts. No IAedu call is needed for the tests. The recorded isolated live A/B checks do not establish scientific effectiveness. Explicit B generation with IAedu makes real API calls; see [ANNOTATION.md](ANNOTATION.md) before doing so. Never commit `.env`, expose credentials, or interpret a simulated `act` as a calendar write.

## Scenario v2 quick start

```bash
python src/benchmark_v2.py validate ../scenario_v2_example.json
python src/benchmark_v2.py import ../scenario_v2_example.json --split train
python src/benchmark_v2.py validate
# When real LLM calls are explicitly authorized:
python eval/run_config_a_v2.py --only working_student_deadline_001
python eval/run_config_b_v2.py --only working_student_deadline_001
python src/proposal_catalog_v2.py eval/runs/<run_id>/B_v2/working_student_deadline_001.json
python src/gate_dataset_v2.py --split train
```

Importing or validating scenarios and importing existing B results make **no model call**. The v2 A and B runners use the same `Proposal` contract, Proposer input adapter, deterministic validator and fixed autonomy rules; B adds the unchanged Critic loop. Legacy A/B runners and data remain available.
