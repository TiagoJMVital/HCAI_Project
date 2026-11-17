# Project overview

> **Current workflow update:** Human annotation now concerns final concrete B proposals directly. Advance scenario annotation remains archived but is no longer required. Schema v2 adds independent profiles, timezone-aware events and typed constraints; see [the benchmark](03_BENCHMARK.md) and [active annotation protocol](04_ANNOTATION_PROTOCOL.md). The original 41 variants and A/B baseline results remain intact. No classifier or configuration C exists. Historical descriptions below refer to the legacy corpus unless marked v2.

## Purpose and scientific question

The [Project Proposal](../../HCAI_Project_Proposal.pdf), §§1 and 3–5, describes a personal calendar assistant that balances deadlines, fixed commitments and flexible preferences while explaining scheduling trade-offs. Its human-centered question is when the assistant should make a proposed change independently and when it should request confirmation. The intended contributions are contextual proposals, independent improvement of their rationales, and a learned autonomy policy. These are research aims, not achieved findings.

The planned comparison has three configurations:

| Configuration | Scheduling and rationale | Autonomy decision | Current state |
| --- | --- | --- | --- |
| A | One Proposer proposal | Fixed rules | Implemented and locally tested; one synthetic IAedu run is recorded. |
| B | Same Proposer, independent Critic, bounded revision loop | Same fixed rules after Critic acceptance; mandatory defer on threshold failure | Implemented and locally tested; one synthetic IAedu run is recorded. |
| C | Same accepted B proposal | Learning-to-Defer classifier replacing fixed rules | Not implemented. Feature and annotation preparation exists. |

All current `act` decisions are **simulated decisions**. No Google Calendar event is read or written. A `proposal_ready` status says that the pipeline completed its current checks; it does not prove that the user's full request is satisfied.

## Current implementation

Python modules in `src/` implement Pydantic contracts, proposal generation, critique, partial operational validation, fixed autonomy rules, benchmark handling and direct v2 proposal annotation. The earlier two-stage workflow remains archived. `eval/` contains A/B runners for both schemas and offline comparison tools. `data/benchmark_manifest.json` describes the original 20 semantic bases and 41 scenario variants; `data/benchmark_v2_manifest.json` is created only when v2 inputs are explicitly imported. The local LLM integration uses the institutional IAedu channel labelled GPT-5.5; Ollama remains selectable. See [Architecture](02_ARCHITECTURE.md), [Benchmark](03_BENCHMARK.md), and [Setup and testing](06_SETUP_AND_TESTING.md).

Verified at this update: 70 local tests pass and the legacy benchmark validator reports 41 scenarios, 20 bases and three grouped training folds. The supplied v2 example validates but has **not** been imported into the v2 manifest. Automated tests use simulated provider responses; they are not a full API or scientific evaluation. Existing local A/B records for `soft_gym_01` are isolated demonstrations, not matched repeated trials. No human labels or gate training dataset were created by this refactor.

## Decisions since the proposal

1. **Primary LLM:** IAedu GPT-5.5 replaced local Ollama as the initial provider to avoid local heavyweight inference. `src/llm.py` keeps Ollama available. The channel ID selects the actual IAedu model; the model label is descriptive metadata.
2. **Orchestration:** Python runners currently orchestrate A and B. The proposed n8n workflow has not been integrated. This is an implementation substitution for the prototype; whether n8n remains a required deliverable needs an author decision.
3. **Data:** The present benchmark is synthetic. The proposal envisages the authors' Google Calendars as well as synthetic conflicts; private calendars and Google authentication have not been connected.
4. **Annotation unit and sequence:** The proposal describes human-annotated scenarios. The current protocol reviews a **specific final B proposal directly**, first for scheduling acceptability, then for `act/defer` only when acceptable. The former advance scenario annotation is preserved as an archive but is no longer required. Critic score and change type vary between proposals from the same scenario, so scenario-only autonomy labels could contradict the gate's decision unit. This refines the method without changing the research question. See [Annotation protocol](04_ANNOTATION_PROTOCOL.md).
5. **Safety before critique:** Pydantic field checks and deterministic calendar checks precede autonomy. The Critic never has direct access to the original calendar or preferences, so its score cannot certify operational validity.

## Boundaries and pending work

The full scheduling constraint engine, request satisfaction checks for all scenarios, independent human rationale assessment, completed annotations, class-diverse training data, the learned gate, configuration C, Google Calendar integration and n8n are pending. Fixed rules and the current Critic score are baselines and diagnostics, not human ground truth. The test-family split must remain sealed while designing the gate. See [Experimental design](05_EXPERIMENTAL_DESIGN.md) and [Roadmap](07_ROADMAP.md).

## Proposal traceability

Evidence names below identify source code or tests, not claims of scientific success.

| Proposal requirement and section | Implementation / document | State | Test evidence | Limitation or deviation | Next action |
| --- | --- | --- | --- | --- | --- |
| Context-aware proposal and explicit trade-offs, §§1, 4 | `src/proposer.py`, `src/models.py`; [Architecture](02_ARCHITECTURE.md) | Implemented | `tests/test_pipeline.py`, one synthetic A/B run | Quality of decisions not established | Human and objective evaluation |
| Calendar/profile context, §§3–4 | `data/profile.json`, `data/scenarios/`, `src/proposer.py` | Synthetic implementation | `src/validate_data.py`, `tests/test_benchmark.py` | No Google Calendar or private data | Decide privacy-safe integration scope |
| Independent scenario/profile contract for gate data, §§3–4 | `src/scenario_v2.py`, `src/benchmark_v2.py`, `src/proposer_v2.py` | v2 adapter implemented | `tests/test_workflow_v2.py`; reference JSON validates | New v2 corpus has not been imported or collected | Freeze family/split plan, then import cases |
| Critic sees proposal and rationale only, §4 | `src/critic.py`, `src/pipeline_b.py` | Implemented | `tests/test_config_b.py` | Cannot verify hidden calendar facts | Independent rationale rubric |
| Iterative feedback and acceptance limit, §4 | `src/pipeline_b.py` | Implemented | `tests/test_config_b.py` | Threshold 4.0 and three revisions are implementation choices | Freeze protocol before evaluation |
| Fixed autonomy baseline A/B, §4 | `src/rules.py`, both runners | Implemented | `tests/test_pipeline.py`, `tests/test_config_b.py` | Heuristic policy may over/under-defer | Compare with adjudicated proposals |
| Learned gate and full C, §4 | `src/gate_dataset_v2.py`; [Roadmap](07_ROADMAP.md) | Export preparation only | `tests/test_workflow_v2.py` | No real human labels, classifier or C | Annotate, freeze features, train on train families |
| Independent annotations and held-out families, §3 | `src/annotation_v2.py`, `src/scenario_v2.py`; [Protocol](04_ANNOTATION_PROTOCOL.md) | Tools implemented; human annotations absent | `tests/test_workflow_v2.py` | Direct proposal label is a justified methodological refinement | Two-author pilot, then formal annotation |
| A/B/C ablation and autonomy metrics, §§4–5 | `eval/run_config_a.py`, `eval/run_config_b.py`, `eval/compare_runs.py` | A/B runnable; evaluation incomplete | Tests and isolated local runs | No C, repeated paired runs or adjudicated reference | Pre-register comparison and collect repeats |
| Matched A/B on v2 inputs, §§4–5 | `eval/run_config_a_v2.py`, `eval/run_config_b_v2.py`, `src/calendar_v2.py` | Mock-tested, no real v2 run | `tests/test_workflow_v2.py` | New v2 corpus and controlled repetitions absent | Collect proposals after split/protocol freeze |
| Scheduling quality, human rationale rubric, §5 | `src/quality_checks.py`, `data/objective_checks.json`; [Design](05_EXPERIMENTAL_DESIGN.md) | Partial | `tests/test_benchmark.py` | Objective request checks cover five scenarios; human rubric not applied | Expand checks and score independently |
| n8n, Ollama, Google API, §3 | `src/llm.py` (Ollama option); Python runners | Partial / absent | `tests/test_llm.py` mocks provider behavior | IAedu primary; no n8n or Google API | Agree deliverable and integration plan |

The proposal's Table 1 and Figures 2–3 illustrate **expected** behavior and target patterns. They are not measured results or labels for the current benchmark.
