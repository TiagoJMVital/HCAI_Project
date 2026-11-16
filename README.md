# Human-Centered AI calendar assistant

This research prototype studies contextual calendar proposals, independent critique and calibrated autonomy. The [Project Proposal](../HCAI_Project_Proposal.pdf) defines three configurations: **A** (Proposer + fixed autonomy rules), **B** (the same Proposer + Critic/refinement + the same rules), and **C** (a future learned Learning-to-Defer gate). A and B currently run on synthetic calendars. All `act` decisions are simulated; no Google Calendar integration or configuration C exists.

## Start here

| Document | Read it for |
| --- | --- |
| [01 Project overview](docs/01_PROJECT_OVERVIEW.md) | Research aims, current evidence, proposal traceability and deviations |
| [02 Architecture](docs/02_ARCHITECTURE.md) | A/B flow, contracts, providers, validation and failure handling |
| [03 Benchmark](docs/03_BENCHMARK.md) | 20 bases, 41 variants, six families, train/test split and limitations |
| [04 Annotation protocol](docs/04_ANNOTATION_PROTOCOL.md) | Independent scenario/proposal forms, adjudication, gate dataset and pilot |
| [05 Experimental design](docs/05_EXPERIMENTAL_DESIGN.md) | A/B/C comparison, metrics, repetitions and evidence boundaries |
| [06 Setup and testing](docs/06_SETUP_AND_TESTING.md) | WSL2 setup, safe IAedu configuration, exact commands and results |
| [07 Roadmap](docs/07_ROADMAP.md) | Completed and pending work, dependencies and author decisions |
| [08 Autonomy policy draft](docs/08_AUTONOMY_POLICY_DRAFT.md) | Discussion examples for proposal-level Act/Defer decisions |

The existing [ANNOTATION.md](ANNOTATION.md) remains the operational command reference for the two-stage annotation workflow. Both authors must annotate independently; no human reference labels have been created yet. Legacy `draft_label` values are preliminary generator metadata, **not** ground truth.

## Local annotation interface

The Streamlit interface edits the same author-specific JSON forms used by the CLI. After installing `requirements.txt` in the WSL2 virtual environment, start it from the repository root:

```bash
source .venv/bin/activate
streamlit run annotation_app.py --server.address 127.0.0.1
```

Open the local URL shown in the terminal (normally `http://localhost:8501`) in the Windows browser. Select `author_a` or `author_b`, open **Scenarios**, and save drafts or validate and complete them. **Proposals** become available after both scenario forms and their adjudication are complete. **Comparison and adjudication** only shows items completed by both authors. The author selector separates work locally; it is not authentication. See [Annotation protocol](docs/04_ANNOTATION_PROTOCOL.md) and [ANNOTATION.md](ANNOTATION.md) for the complete workflow. Starting this app does not call IAedu.

The annotation page now starts with a **read-only weekly calendar** (Monday–Sunday, 24-hour times). Use the week arrows to navigate; the initial week comes from the scenario dates. Colored blocks show event categories, while every block also says **Fixo** or **Flexível**. A dashed amber band marks a requested interval only when a narrow deterministic parser can identify it safely. Outlined events temporally overlap that band; overlap alone is **not** proof of a hard-constraint violation. The original event table remains under **Ver eventos em tabela**. In the proposal phase, an **Calendário original / Calendário proposto** switch appears only when the final changes pass the existing structural and operational checks. A preview never edits a calendar and does not certify that the request is satisfied. See the [annotation protocol](docs/04_ANNOTATION_PROTOCOL.md#weekly-calendar-and-request-highlight) for supported interval phrases and limits.

## Quick local verification

From the WSL2 repository root, after following the environment steps in [Setup and testing](docs/06_SETUP_AND_TESTING.md):

```bash
python src/validate_data.py
python -m pytest -q tests
```

The currently verified local result is **54 passing tests** and a valid 41-variant benchmark. These tests use mocked LLM responses. The only recorded live IAedu A/B checks use one synthetic scenario each and do not establish scientific effectiveness. Running A or B with IAedu makes real API calls; see the setup document before doing so. Never commit `.env`, expose API credentials, or interpret a simulated `act` as a calendar write.
