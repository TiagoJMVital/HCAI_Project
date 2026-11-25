# Direct proposal annotation protocol

The unit of human judgment is a **concrete final B proposal**, identified by `proposal_id`, linked to a standalone schema `2.0` scenario. Advance annotation of scenarios is no longer required. The old two-stage forms and 41 legacy scenarios are preserved only in the local archive described in [archive/README.md](archive/README.md).

## Prepare scenarios and proposals

Create a scenario using [`scenario_v2_example.json`](../scenario_v2_example.json) and the exact Pydantic contract in `src/scenario_v2.py`. Keep `schema_version`, `scenario_id`, `family_id`, `profile`, `now`, `calendar.events`, and `user_request`. Events need unique IDs, ISO 8601 timestamps with offsets, and start before end. Protect-event rules must reference existing events. Intentional calendar overlaps are allowed. Do not add human labels or expected schedules.

```bash
python src/benchmark_v2.py validate /path/to/scenario.json
python src/benchmark_v2.py import /path/to/scenario.json --split train
python src/benchmark_v2.py validate
```

Use `--split test` only for a reserved family. All variants of one family must use the same split. The importer refuses overwrites. Imported files live in `data/scenarios/`; `data/benchmark_manifest.json` carries split assignments. Import does not invoke an LLM.

When generation is authorised, run B explicitly and import the printed result path. A remains available for paired comparison:

```bash
python eval/run_config_a_v2.py --only <scenario_id>
python eval/run_config_b_v2.py --only <scenario_id> --critic-threshold 4.0 --max-refinements 3
python src/proposal_catalog_v2.py eval/runs/treino/<family>/<scenario_id>/<run_id>/B/<scenario_id>.json
python src/proposal_catalog_v2.py --training
```

The first two commands call the configured LLM; both catalogue commands only read local results. `--training` imports every eligible terminal B result from the authoritative training split idempotently. An already imported proposal remains canonical; otherwise the earliest eligible result by generation time and run ID is selected, without considering Critic score, scheduling quality or autonomy outcome. Eligibility is content-based, not status-only: every iteration must contain a complete proposal and consistent deterministic validation; valid iterations require a real result calendar and Critic response; scientific terminal statuses must agree with the final iteration; and record-level technical error fields are forbidden. The source run hash is checked again whenever the active training catalogue is loaded. A failed check quarantines the imported proposal from annotation and gate export without deleting it or its annotations. Results are grouped by scenario, then retain their unique run ID and configuration directory. A historical run-first result or `B_v2/` directory remains readable. The B result and immutable imported artifact retain the proposal, rationale, Critic history/scores, validation report and run/provider metadata. Importing a deterministically invalid but technically complete scientific outcome is possible for scheduling-quality review; it cannot become an eligible gate example. Technical failures and incomplete outputs are rejected. Failed attempts are never active runs; new failures retain their raw structured-output evidence and sanitized diagnostics under `eval/technical_failures/` for audit. Imported artifacts are in `data/proposals/`; the result remains in `eval/runs/`. Opening the UI never generates proposals.

New B runs additionally record the complete in-memory result calendar for each Critic-evaluated iteration. The Critic sees it with the structured proposal, rationale, timezone and limited validation report; original request and full profile stay outside the Critic input. Historical B artifacts lack this optional field and remain readable without conversion. The Streamlit iteration expander shows the feedback, per-iteration result calendar and final unresolved weaknesses when present.

Runs marked `critic_policy_version=plausibility_review_v1` require a structured plausibility review on every new Critic response. The UI shows severity, explicit revision decision, evidence, suggested improvement, numeric result and revision cause. Older artifacts show the plausibility assessment as **unavailable**, not as `revision_required=false`. A review requested by the Critic is independent of a human `act/defer` annotation; below-policy B outputs are excluded from normal gate training by the existing exporter.

New runs marked `uncertainty_review_v2` additionally show conditions the Critic could not verify. Read their subject, missing evidence and possible impact separately from the technical validation and your human autonomy judgment. A final empty list means none identified by that Critic response; an absent list in an older run means the question was not structured then. Earlier conditions remain in iteration history, with resolution unconfirmed if they disappear later. `proposal_ready` is a quality-policy outcome, not a guarantee of operational availability or authorization. The annotation form and current gate features have not changed.

In current B runs, each revised iteration also records the prior Critic concern, feedback to the Proposer, and whether the operations or rationale changed. The Proposer may retain operations after re-evaluating the practical concern; inspect its rationale and the next Critic judgment to see whether the doubt remains. These records describe the review process, not a verified improvement in scheduling. The Critic still has no direct access to the original request or full profile.

## Independent review in Streamlit

```bash
streamlit run annotation_app.py --server.address 127.0.0.1
```

Open the printed local URL in the browser. Pick `author_a` or `author_b`, then **Propostas**. Select a profile family and then one of its available training scenarios. The primary independent-review page shows the complete request, synchronized original/proposed calendars, a complete structured change table, and the scenario's hard constraints, soft constraints, preferences and relevant context. Full event titles, times and durations are available in calendar tooltips; deleted events are not presented as scheduled in the proposed calendar. Critic scores, verdicts, revision history and rule-based autonomy decisions are deliberately absent from this page and remain available only in separate diagnostic/comparison views. The weekly calendar is read only; overlap means temporal overlap, not automatically a hard-rule failure. Invalid scientific outcomes show their proposed operations but are never misrepresented as a valid applied calendar.

Progress is calculated separately for the selected reviewer, by family and overall. The interface never reveals the other reviewer's decision during independent annotation and offers direct navigation to the next unannotated scenario.

Each author independently records:

- `scheduling_acceptable`: `yes` or `no`;
- for `yes`, `autonomy_decision`: `act` or `defer`;
- `primary_reason`, optional `additional_reasons` for defer, and a written `justification`.

For `defer`, the reason vocabulary is `clarification_required`, `confirmation_required`, `high_impact`, `third_party_impact`, or `preference_conflict`. An `act` decision uses a free-text primary reason. For `no`, leave autonomy blank: this is a scheduling-quality rejection, not a defer label. A technically invalid proposal can only be completed as a quality rejection. Incomplete drafts can be saved and reloaded. The JSON forms live separately in `data/annotations/author_a/` and `author_b/`. The author selector is only operational separation, not authentication; use separate local sessions and do not inspect the other author's files before both reviews are complete.

## Compare and adjudicate

After both reviews are complete, open **Comparação e adjudicação**. It shows differences, observed autonomy agreement and Cohen's kappa when applicable. Discuss disagreements, enter a consensus decision and rationale, record disagreement fields and the adjudicator, then save. `data/annotations/adjudicated/` stores the consensus separately with hashes of both originals. The system does not invent a consensus or overwrite individual reviews. A one-class or very small sample may make kappa undefined or unstable.

## Export for the future gate

```bash
python src/gate_dataset_v2.py --split train
```

The exporter writes `data/gate_datasets/train.jsonl` and an exclusions report. It requires an integrity-verified, technically valid, accepted B proposal, two complete reviews and a current complete consensus with acceptable scheduling and an `act/defer` label. Quarantined imports are reported as `source_run_integrity_failed`; their proposal and human annotation files remain untouched. It excludes failures and missing/quality-rejected cases; scenario count is not example count. Identifiers and human reasons are metadata, never predictive features. The test split remains locked: `--split test --unlock-test` is reserved for after freezing features, model and evaluation policy. Never tune using test-family labels. No classifier is trained by this command.

See [docs/04_ANNOTATION_PROTOCOL.md](docs/04_ANNOTATION_PROTOCOL.md) for methodological detail and [docs/08_AUTONOMY_POLICY_DRAFT.md](docs/08_AUTONOMY_POLICY_DRAFT.md) for provisional discussion examples.
