# Synthetic benchmark

## Independent schema v2 extension

The original 20 bases/41 variants remain unchanged in `data/scenarios/`. New inputs are imported separately into `data/scenarios_v2/`; split assignments live in `data/benchmark_v2_manifest.json`. The supplied [`scenario_v2_example.json`](../../scenario_v2_example.json) is a reference example, not an automatically imported or labelled case. Validate it with `python src/benchmark_v2.py validate ../scenario_v2_example.json`; import explicitly with `python src/benchmark_v2.py import ../scenario_v2_example.json --split train` after deciding its family split. Existing scenarios are never auto-converted, as that would invent profile fields or timezones.

**Required contract:** `schema_version: "2.0"`, `scenario_id`, `family_id`, `profile`, `now`, `calendar: {events: [...]}`, `user_request`. Profile requires `profile_id`, `description`, IANA `timezone`, 1–5 `priorities` map, typed `hard_constraints`, weighted `soft_preferences` and `autonomy_preferences`. Events require `id`, `title`, timezone-aware ISO `start/end`, `category`, 1–5 `importance`, `fixed`, `participants` and `description`. Typed hard rules are currently `protect_events_by_category` (`event_categories`), `protect_events_by_id` (`event_ids`) and `daily_time_window` (`start/end`). Unknown rule types are rejected until supported. Event IDs must be unique, rule event references resolve, start precedes end and offsets agree with the profile timezone. Intentional calendar overlaps are allowed. Scenarios contain no labels, expected solutions or human decisions. Profiles need not represent students.

The split is metadata outside the scenario. Freeze new family definitions and planned train/test assignments before collection. All variants in one family stay in one split; test labels stay locked until the model and analysis plan are frozen. The supplied example alone is not an adequate benchmark. The inventory below describes the older corpus.

## Inventory and provenance

`src/make_seed_scenarios.py` produced the original ten synthetic cases. `src/make_benchmark.py` preserves them and builds the current manifest in `data/benchmark_manifest.json`: **20 semantic base scenarios, 41 variants, six families**. A base groups variants of one scheduling situation; a family groups related bases and is the train/test separation unit. `data/scenarios/<scenario_id>.json` holds each request, simulated time, calendar and scenario metadata. `data/profile.json` holds common priorities, hard constraints, flexible commitments and scheduling preferences.

| Family | Split | Bases | Variants | Main focus |
| --- | --- | ---: | ---: | --- |
| `hard_class` | train | 3 | 6 | Fixed academic commitments and alternative slots |
| `soft_gym_deadline` | train | 4 | 9 | Exercise routines versus study/deadline pressure |
| `ambiguous_health` | train | 4 | 8 | Health-related ambiguity and differing specificity |
| `hard_fixed_travel` | test | 1 | 2 | Fixed travel obligations |
| `soft_study_social` | test | 4 | 8 | Study time, social commitments and soft priorities |
| `ambiguous_supervisor` | test | 4 | 8 | Supervisor requests, importance and ambiguity |
| **Total** | | **20** | **41** | **23 train / 18 test variants** |

The manifest records `scenario_id`, `base_id`, family, split, category, factor values and a design note. Categories are `hard`, `soft` and `ambiguous`, but category is a descriptor, not a human autonomy label. The original ten include `draft_label` metadata; the 31 newly added variants do not acquire human labels through generation. Never use `draft_label` or a category as reference truth.

## What varies

The generator varies decision-relevant factors such as event importance, fixed versus flexible commitments, urgency, ambiguity, timing options, affected people, and impact. For example, `hard_class_01`/`hard_class_02` keep a fixed class relevant while changing scheduling pressure; `soft_gym_01`/`soft_gym_02`/`soft_gym_03` explore the gym/deadline trade-off; `health_specificity_01`/`health_specificity_02` vary how explicitly the request defines the intended health action. These are **scenario inputs**, not observed model behavior. Consult each scenario JSON and `design_note` before using it as a specific example in a report.

The benchmark aims to include hard constraints, soft preference conflicts, ambiguous/high-impact cases, multiple acceptable outcomes, plausible autonomous actions and cases requiring confirmation. Coverage by these design categories does not guarantee both human label classes after concrete proposals are annotated. A single base may yield different proposals, hence different labels.

## Split and leakage control

The manifest fixes three training families (`hard_class`, `soft_gym_deadline`, `ambiguous_health`) and three held-out test families (`hard_fixed_travel`, `soft_study_social`, `ambiguous_supervisor`). `src/benchmark.py` checks that each base belongs to one family/split and prepares three grouped folds from training families. `src/gate_dataset.py` also groups proposal rows by family/base; multiple runs of the same scenario must remain in the same group. Do not reshuffle the split after looking at test labels, outputs or error patterns.

Potential leakage paths include near-identical requests across families, a shared profile or prompt that reveals category cues, repeated proposals from the same base, and tuning fixed rules/feature heuristics using held-out outcomes. The current training side has only three families; grouped cross-validation estimates may be unstable and may omit a whole category in a fold. Report family-level performance and uncertainty when the final dataset exists. The preliminary labels on the ten seeds are skewed by category; they are not evidence of the final proposal-label distribution.

## Extending the benchmark

1. Choose a new **semantic** base or a controlled variant that changes a decision-relevant factor. Record the hypothesis in `design_note`; changing only a name/date is inadequate.
2. Keep the base within its assigned family and split. For a new family, decide its split using training design criteria *before* inspecting test outcomes. Do not use test labels to guide gate design.
3. Add construction logic in `src/make_benchmark.py` and keep generated scenario JSON and manifest consistent. If the addition affects the frozen evaluation set, treat it as a new benchmark version and document the rationale rather than silently changing it.
4. Run `python src/make_benchmark.py`, `python src/validate_data.py` and `python -m pytest -q tests`. Check that the scenario remains realistic and allows clear, independently annotatable outcomes.
5. Add objective request checks to `data/objective_checks.json` only where a condition is genuinely machine-checkable. Otherwise leave request satisfaction for human assessment; do not translate a free-text judgement into an unjustified binary rule.

Only five current requests have partial objective checks in `data/objective_checks.json`. `src/quality_checks.py` reports `unknown` for uncovered request satisfaction. Neither those checks nor the Critic's score replace human assessment of acceptable schedules. See [Experimental design](05_EXPERIMENTAL_DESIGN.md).
