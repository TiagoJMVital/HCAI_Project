# Active benchmark: scenario schema 2.0

The official corpus is `data/scenarios/`, indexed by `data/benchmark_manifest.json`. It currently contains **one** imported scenario, `working_student_deadline_001`, whose source JSON was moved byte-for-byte during cleanup. The 20-base/41-variant legacy benchmark is preserved in `archive/legacy_v1/` and Git history for consultation; it is not the active benchmark or an automatically converted v2 corpus. Converting it would require inventing profiles and timezone-aware fields.

## Scenario contract

[`working_student_deadline_001.json`](../data/scenarios/working_student_deadline_001.json) is the checked-in reference example. `src/scenario_v2.py` enforces exactly `schema_version: "2.0"` and the fields `scenario_id`, `family_id`, `profile`, `now`, `calendar.events`, `user_request`. A profile has `profile_id`, `description`, `timezone`, `priorities`, `hard_constraints`, `soft_preferences`, and `autonomy_preferences`; events have `id`, `title`, `start`, `end`, `category`, `importance`, `fixed`, `participants`, and `description`. The validator checks unique IDs, IANA timezones, timestamp offsets, chronology, importance/priorities 1–5 and references from typed constraints. Intentional event overlap is allowed. The contract has no human label, expected proposal or outcome. It supports multiple profile types, not just students.

## Import and split

```bash
python src/benchmark_v2.py validate /path/to/scenario.json
python src/benchmark_v2.py import /path/to/scenario.json --split train
python src/benchmark_v2.py validate
```

Choose `train` or `test` before import. Every variant of a `family_id` stays in the same split; the importer rejects a conflicting split or duplicate scenario. Repeated proposals for one scenario inherit its family. Test families must not be used to tune prompts, fixed rules, gate features or thresholds. Grouped training folds are prepared by `src/gate_dataset_v2.py` when enough training families exist. The current single-family corpus is too small for meaningful grouped cross-validation or scientific evaluation.

To add a scenario, copy the reference shape, give it a new scenario ID and a scientifically meaningful family, validate it, assign the family split, then import. Vary impact, ambiguity, conflicts, flexibility and feasible options rather than only names or dates. Document any benchmark version/family decision before generating proposals. No scenario import makes an LLM call.
