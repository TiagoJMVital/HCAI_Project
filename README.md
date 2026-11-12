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

## Quick local verification

From the WSL2 repository root, after following the environment steps in [Setup and testing](docs/06_SETUP_AND_TESTING.md):

```bash
python src/validate_data.py
python -m pytest -q tests
```

The currently verified local result is **41 passing tests** and a valid 41-variant benchmark. These tests use mocked LLM responses. The only recorded live IAedu A/B checks use one synthetic scenario each and do not establish scientific effectiveness. Running A or B with IAedu makes real API calls; see the setup document before doing so. Never commit `.env`, expose API credentials, or interpret a simulated `act` as a calendar write.
