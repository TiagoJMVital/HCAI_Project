# Current human annotation protocol (scenario schema 2.0)

The unit of judgement is a **concrete final proposal**, identified by `proposal_id`. A scenario has no human label or expected answer in its JSON. The former two-stage workflow is retained in `src/annotation_workflow.py`, `src/annotation_ui.py`, `src/gate_dataset.py` and `data/annotation_work/` for historical access. It is **not a prerequisite** for schema v2 annotation. No old forms or results are migrated automatically.

## 1. Prepare an independent scenario

Use [`scenario_v2_example.json`](../scenario_v2_example.json) as a data-format example. A v2 scenario has `schema_version`, `scenario_id`, `family_id`, `profile`, `now`, `calendar.events` and `user_request`; see [the benchmark document](docs/03_BENCHMARK.md) for the full profile/event fields. Timestamps require an ISO 8601 offset consistent with the profile's IANA timezone. Calendar overlaps are permitted because they may be intentional benchmark conflicts. Do not place labels, expected schedules or human evaluations in scenario files.

From `HCAI_Project/`:

```bash
python src/benchmark_v2.py validate ../scenario_v2_example.json
python src/benchmark_v2.py import ../scenario_v2_example.json --split train
python src/benchmark_v2.py validate
```

Choose the split **before** importing a family. The importer refuses a family split across train/test, including a conflict with an identically named legacy family. It refuses to overwrite an imported scenario. The v2 manifest at `data/benchmark_v2_manifest.json` contains only IDs and split assignments; scenarios live separately in `data/scenarios_v2/`. Keep all variants of a family in one split. Test families remain reserved.

## 2. Generate or import one B proposal

Generation is an **explicit command**; opening Streamlit never calls a model. The following command makes real requests to the configured provider, so run it only when API use is authorized:

```bash
python eval/run_config_b_v2.py --only working_student_deadline_001
python src/proposal_catalog_v2.py eval/runs/<run_id>/B_v2/working_student_deadline_001.json
```

For an already generated v2 B result, run only the second command. The importer checks the result's scenario/family/profile/split, final proposal and iteration history, recalculates technical validation, assigns a deterministic unique `proposal_id`, and writes an immutable artifact in `data/proposal_sources_v2/`. It stores provider/model, prompt hashes, Critic score, iterations, validation and run metadata. A technically invalid final proposal may remain available for a **quality rejection**; it cannot silently become a gate training example. B's own fixed-rule decision is not the human label.

The Proposer receives the complete v2 context. The Critic receives only the structured proposal and its rationale, never the original request, calendar or profile through a separate channel. For v2, the Proposer prompt asks for timezone-aware change timestamps. The original A/B runners, prompts, rules and legacy scenarios are unchanged.

## 3. Evaluate independently in the web interface

```bash
source .venv/bin/activate
streamlit run annotation_app.py --server.address 127.0.0.1
```

Open the local URL printed by Streamlit in the Windows browser (usually `http://localhost:8501`). In **Propostas v2**, select `author_a` or `author_b`; filter by profile, family and state; select a proposal or use the previous/next buttons. Read the request, complete profile, weekly original calendar, final changes, rationale, technical validation and Critic score/iterations. Switch to the proposed calendar only if the in-memory simulation passed. Fixed/flexible labels and added/moved/removed styles remain visible. Added events have neutral preview metadata because the current `Proposal` contract lacks category and participants. The displayed Critic score evaluates reasoning, not scheduling validity. The author selector is operational separation, **not authentication**; do not inspect the other author's file while annotating.

The author form is saved in `data/annotation_work_v2/<author>/<proposal_id>.json`. Save incomplete drafts at any point; drafts reload when revisiting the proposal. Save before navigating away. Completion requires:

1. `scheduling_acceptable = yes/no`.
2. If **yes**, `autonomy_decision = act/defer`. If **no**, leave the autonomy decision empty: this is a quality rejection, not a `DEFER` label.
3. A nonempty `primary_reason` and `justification`. For `defer`, the primary reason must be one of `clarification_required`, `confirmation_required`, `high_impact`, `third_party_impact`, `preference_conflict`; additional reasons are optional. For `act` or a quality rejection, the primary reason is free text.

Completion is checked by Pydantic. A saved complete review needs explicit confirmation before an edit; a completed consensus freezes the individual reviews. Files are written atomically and revision checked to prevent silent concurrent overwrites. Drafts and consensus are separate from the immutable proposal artifact.

## 4. Compare and adjudicate

After both authors finish a proposal, open **Consenso v2**. The page shows their completed reviews side by side, disagreement fields, observed `act/defer` agreement and Cohen's kappa where calculable. A small or single-class sample may make kappa undefined or unstable. Discuss disagreements, fill the consensus fields and identify who adjudicated. The consensus is stored separately in `data/annotation_work_v2/adjudications/<proposal_id>.json`, with SHA-256 references to both original reviews. The interface never copies an author's decision as consensus automatically. Original reviews remain intact.

## 5. Export supervised examples

```bash
python src/gate_dataset_v2.py --split train
# Only after the feature extractor, classifier and evaluation policy are frozen:
python src/gate_dataset_v2.py --split test --unlock-test
```

Output is `data/gate_datasets_v2/<split>.jsonl`, with a parallel `.exclusions.json` explaining each omitted proposal. Eligible rows require a technically valid final proposal, an accepted B run, two completed independent reviews, a completed consensus and `scheduling_acceptable=yes`. A quality rejection has no gate label. Features use proposal/context variables and Critic score; IDs and split are metadata outside `features`. Human decisions, reasons and justifications never enter predictive features. There is no classifier training in this workflow. Use `grouped_folds` from `src/gate_dataset_v2.py` only on training rows for family-grouped validation.

## Scientific limits

Typed v2 checks cover references, timezone offsets, fixed/category/id protection, positive durations, daily windows and protected-event overlaps. Descriptions in natural language, soft preferences, request satisfaction, correctness of inferred add-event metadata and autonomy suitability are **not automatically proven**. In particular, a technically applicable proposal can still be marked `scheduling_acceptable=no`. Do not call an invalid proposal a normal `DEFER` example. Keep test families untouched while developing policy or feature definitions. The [autonomy policy draft](docs/08_AUTONOMY_POLICY_DRAFT.md) is discussion guidance, never ground truth.
