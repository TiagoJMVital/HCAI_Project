# Aggregate constraints: technical feasibility study (phase 4)

> Phase-4 analysis is retained below as a historical design record. Phase 5 implemented only the minimum-duration subset; see the addendum at the end. Statements below about no aggregate implementation describe the phase-4 state.

**Status:** design study only; no changes to schema, validator, simulator, agents, active manifest or historical runs. Dataset input: `Cenarios_v2_100_normalizados.zip` (SHA-256 `f56332e6e892ebe3682acfb7851afcf47c35a9cebca2f64d33f82abe5113df1b`). The 25 entries below were triaged in phase 3; phase 4 found that two of them are actually specific-event protections and can be represented with existing `protect_events_by_id`. The remaining **23** need further author/technical decisions; “needs validator” is a design flag, not a certified impossibility for every request.

## Problem and affected scenarios

`protect_events_by_category` freezes *every* event in a category under `calendar_v2.simulate`, including `fixed=false` events. It cannot express “preserve 30 weekly work hours while moving individual blocks”, “keep three exercise sessions”, or “finish a task before a deadline”. Treating prose in `description` as if it were checked creates a false guarantee. Restriction of a rule to fixed IDs may free changes, but it does not preserve a quantitative goal. The table gives the full original phase-3 inventory; the last column records phase-4 action.

| Scenario | Rule(s) under review | Phase-4 action |
|---|---|---|
| `content_creator_medical_emergency_sponsor_001` | `sponsor_deadline` | Pending: no aggregate rule implemented |
| `freelancer_flexible_apartment_hunting_closing_001` | `weekly_hours` | Pending: no aggregate rule implemented |
| `freelancer_flexible_emergency_dentist_padel_tournament_001` | `weekly_hours` | Pending: no aggregate rule implemented |
| `freelancer_flexible_girlfriend_day_deadline_001` | `weekly_project_hours` | Pending: no aggregate rule implemented |
| `freelancer_flexible_hackathon_prep_daily_syncs_001` | `daily_client_syncs;weekly_hours` | Pending: no aggregate rule implemented |
| `freelancer_flexible_industry_networking_dinner_001` | `weekly_hours` | Pending: no aggregate rule implemented |
| `freelancer_flexible_medical_appointment_birthday_dinner_001` | `weekly_hours` | Pending: no aggregate rule implemented |
| `freelancer_flexible_tax_audit_accountant_meeting_001` | `weekly_hours` | Pending: no aggregate rule implemented |
| `freelancer_flexible_tech_podcast_interview_deadline_001` | `weekly_hours` | Pending: no aggregate rule implemented |
| `freelancer_flexible_workshop_client_launch_001` | `weekly_hours` | Pending: no aggregate rule implemented |
| `nurse_shift_worker_masters_als_recertification_mock_defense_001` | `thesis_daily_time` | Pending: no aggregate rule implemented |
| `nurse_shift_worker_masters_clinical_data_collection_001` | `thesis_daily_time` | Pending: no aggregate rule implemented |
| `nurse_shift_worker_masters_makeup_exam_001` | `thesis_daily_time` | Pending: no aggregate rule implemented |
| `nurse_shift_worker_masters_night_shift_cover_001` | `thesis_daily_time` | Pending: no aggregate rule implemented |
| `nurse_shift_worker_masters_night_shift_swap_001` | `thesis_daily_time` | Pending: no aggregate rule implemented |
| `nurse_shift_worker_masters_rail_strike_commute_001` | `thesis_daily_time` | Pending: no aggregate rule implemented |
| `nurse_shift_worker_masters_shift_changes_001` | `thesis_daily_time` | Pending: no aggregate rule implemented |
| `nurse_shift_worker_masters_shift_overtime_chapter_deadline_001` | `thesis_daily_time` | Pending: no aggregate rule implemented |
| `nurse_shift_worker_masters_thesis_deadline_moved_001` | `thesis_daily_time` | Pending: no aggregate rule implemented |
| `nurse_shift_worker_masters_thursday_cover_001` | `thesis_daily_time` | Pending: no aggregate rule implemented |
| `university_professor_exam_grading_lecture_invite_001` | `scheduled_classes_mandatory` | Specific-event rule applied |
| `university_professor_exam_week_invigilation_grading_006` | `exam_invigilation_mandatory` | Specific-event rule applied |
| `university_professor_grant_panel_resit_exam_005` | `grant_panel_mandatory;resit_exam_deadline` | Pending: no aggregate rule implemented |
| `university_professor_international_conference_exam_creation_002` | `conference_keynote_mandatory;exam_paper_ready_before_travel` | Pending: no aggregate rule implemented |
| `working_student_transit_strike_commute_delay_006` | `work_and_class_punctuality` | Pending: no aggregate rule implemented |

## Current implementation and where checks occur

- [`src/scenario_v2.py`](../src/scenario_v2.py) supports only `protect_events_by_category`, `protect_events_by_id` and `daily_time_window` (plus IDs, dates, offsets and references). Prose descriptions, priorities and soft preferences are data, not executable predicates. Schema is strict (`extra="forbid"`); adding an unrecognized field to a 2.0 scenario would fail validation.
- [`src/calendar_v2.py`](../src/calendar_v2.py) simulates `add`/`move`/`delete` without real-calendar writes. It rejects changing fixed/protected events, wrong timezone or duration, and overlap with protected events. It checks each operation as it goes, then checks the final events for windows/overlaps. An aggregate checker should assess the **final calendar**, so an intermediate delete followed by replacement must not fail just because the temporary state is short of the goal. Existing `Proposal` also forbids changing the same event twice.
- [`src/models.py`](../src/models.py) has `Change` fields `type`, `event_id`, `title`, `to_start`, `to_end` and related source fields. An `add` has no category, importance, participants, task identity or completion evidence; simulation assigns neutral category `other`, importance 3 and default duration 1 h if no end is supplied. Counting such events toward work/thesis/exercise would be unjustified.
- [`src/proposer_v2.py`](../src/proposer_v2.py) receives full profile and calendar and can reason about prose, but its output does not prove an aggregate target or an external fact. [`src/critic.py`](../src/critic.py) reviews the final simulated calendar and rationale, without direct profile or request; it can question sustainability, not validate a typed target it never received. [`src/rules.py`](../src/rules.py) decides fixed-rule autonomy for A/B; it is not an aggregate validator.
- [`eval/run_config_a_v2.py`](../eval/run_config_a_v2.py) and [`src/pipeline_b.py`](../src/pipeline_b.py) use the same simulator. [`src/proposal_catalog_v2.py`](../src/proposal_catalog_v2.py) recomputes simulation before importing B proposals. [`src/gate_dataset_v2.py`](../src/gate_dataset_v2.py) exports only adjudicated, technically valid B proposals; it does **not** infer ACT/DEFER from constraint descriptions. A new technical rule would change which proposals can be accepted/exported; it must apply uniformly to A/B/C and be versioned for fair comparison.

## Requirement classes and deterministic boundary

| Class | What can be checked with sufficient typed data | What remains outside the check |
|---|---|---|
| Total duration | Sum union of intervals for selected activity/task across a defined local period, after simulation; compare `>=`/`<=`/`==` against minutes. | Calendar reservation does not prove work finished; unknown category/task ID of new events; partial horizon. |
| Frequency | Count distinct qualifying sessions in a period, with a minimum duration and task/category tag. | Whether sessions actually occur, equivalence of split/merged sessions, external facility access. |
| Deadline | Ensure a labelled block ends before `deadline_at`, or a confirmed milestone event exists by then. | Completion of exam paper, upload, approval, actual delivery; calendar time alone is weak evidence. |
| Rest | For explicit sleep events with trusted labels, calculate per-night duration or gap between named shifts. | Human recovery, sleep quality, family caregiving, travel and unrecorded sleep. These remain Critic/human judgments. |
| Externally changed fixed event | With a trusted change notice, exempt a named original event from immutability only for the stated before/after; still validate the new result. | Authenticity of notice and third-party agreement; not a blanket permission to move fixed events. |

## Three strategies

| Strategy | Potential recovery | Complexity / regression risk | A/B/C and historical impact | Assessment |
|---|---|---|---|---|
| A. JSON only | Up to the 26 phase-4 specific-event candidates; **cannot safely certify** the 23 remaining aggregate/temporal cases by merely changing prose. | Low code risk; high risk of weakening semantics if category rules are simply removed. | Existing schema/runs remain readable; comparison unchanged. | Appropriate for the current dataset review, with manual pending status. |
| B. Minimal typed extension | Potentially addresses recurring nurse thesis and freelancer weekly-hours patterns (19 scenarios), plus selected deadline cases; **not a guarantee of 23 recoveries**. | Medium to high: scenario contract, Proposal metadata, simulator and tests; dataset migration requires author confirmation. | Must version rule semantics and rerun A/B/C with same checks; historical results stay labelled under old validator. | **Recommended next technical step only after authors approve concrete targets and metadata.** |
| C. Broad temporal/dependency language | Could cover most narrative constraints in principle, including travel and dependencies. | High complexity, unverifiable external facts, substantial prompt/contract changes; hard to test on 100 cases. | Strong comparability and reproducibility risk. | Disproportionate for this academic dataset now. |

**Recommendation:** finish A for the safe local data corrections, keep unresolved cases flagged, then design a narrowly scoped B for *explicit, measurable* total duration/frequency targets that recur in several profiles. Do not implement deadline “completion” or human sustainability as deterministic success without evidence. This is a decision proposal, not an approval to change production code.

## Proposed minimal contract, not yet implemented

A possible optional, versioned addition **after** author approval is an `aggregate_requirements` list. Because the current v2.0 model forbids unknown fields, it cannot be silently inserted into existing `schema_version: "2.0"` files. Use an explicit compatible version/migration plan, or an external requirements manifest keyed by scenario and hashed with it, to preserve the shared v2.0 contract. Example *conceptual only*:

```json
{
  "id": "weekly_work_minutes",
  "kind": "duration_total",
  "selector": {"task_id": "client_work"},
  "period": {"start": "2027-04-12T00:00:00+01:00", "end": "2027-04-19T00:00:00+01:00"},
  "operator": ">=",
  "value_minutes": 1800,
  "coverage": "complete_period_required"
}
```

Required: stable rule ID, kind, selector, closed-open period with timezone, operator and integer target; selectors should be explicit task IDs or vetted categories, not unparsed natural-language guesses. For frequency, add `min_session_minutes`, `count` and period. Deadline checks require `deadline_at` and a trustworthy meaning of “completed” that a calendar event generally cannot supply. Constrain operators to `>=`, `<=`, `==` only where their semantics are tested. Count actual elapsed minutes for intervals crossing midnight; apportion to local calendar days when the rule is daily, with DST handled by timezone-aware boundaries. A partial horizon or missing category/task metadata returns **unknown/needs review**, never silent pass or fabricated failure. The final calendar alone is evaluated after all changes. Fixed and explicit ID/category protections still apply separately; aggregate rules do not override them.

Example before/after *conceptual*, not a patch to existing JSON:

```json
{"id":"weekly_hours","description":"Maintain 30 hours of client work this week","rule_type":"protect_events_by_category","event_categories":["work"]}
```

```json
{"id":"weekly_hours","kind":"duration_total","selector":{"task_id":"client_work"},"period":{"start":"2027-04-12T00:00:00+01:00","end":"2027-04-19T00:00:00+01:00"},"operator":">=","value_minutes":1800,"coverage":"complete_period_required"}
```

The second example would require trusted tags on existing **and newly added** work events; it cannot simply replace the first rule in schema v2.0. A rule expressed as “preserve the original total” needs an explicit baseline and a decision about whether the baseline is complete. Any verified change to a fixed event should identify the exact event and authorized new timing, not make all fixed events movable.

## Necessary changes if strategy B is later approved

1. Extend or version `scenario_v2.py` rule representation, with precise backward read of v2.0; decide whether a sidecar manifest is preferable to changing the shared contract.
2. Extend `models.Change` and provider-facing JSON schema to carry task/category/duration metadata for added events, with validation and provenance; maintain old-run decoding separately. Avoid inferring categories from titles.
3. In `calendar_v2.simulate`, compute final-state aggregate checks after all operations. Return `pass`, `fail`, or `unknown` per rule with concrete evidence and messages such as `weekly_hours: only 24h 30m of 30h required` or `weekly_hours: unknown; added event has no trusted task tag`. Do not mark unknown as valid.
4. Apply the new validator version uniformly in runners A/B, pipeline B, proposal import and gate export; store validator version/hash in results. Historical runs remain unmodified and must not be compared as though they used the new check.
5. Review Proposer instructions only to explain the new typed rule, without changing A alone; Critic should receive final validation results but keep its human quality role. Fixed autonomy rules and future gate features should not silently change.

## Test plan and methodological risks

Unit tests: weekly totals after move/delete/add, replacement after intermediate delete, overlap and double counting, interval across midnight/DST, partial calendar returns unknown, missing task tags on `add`, per-day sleep with overnight events, frequency with short sessions, before/after deadline semantics, fixed-event authorization narrowly scoped, old v2.0 unchanged. Integration tests: A/B same validator, proposal catalog rejects stale result calendars, gate export excludes invalid/unknown cases, historical run remains readable, family split unaffected. Human review still assesses whether booked time achieves the task, whether rest is adequate, and whether external availability is verified.

Estimated effort (qualitative, no run-time measurement): contract/versioning **medium**, added-event metadata **medium-high**, final-state duration/frequency checks **medium**, deadlines/completion **high**, fixed-event external authorization **high**, integration/regression tests **medium-high**. Before implementation, authors must decide: which 23 scenarios truly require each measurable target; whether the horizon is complete; how new events obtain trustworthy task tags; whether “deadline met” means scheduled preparation or verified completion; and how to version the already shared schema 2.0. Until then, the current protection remains and cases are pending rather than being presented as valid solutions.

## Phase 5 implementation addendum (2026-11-20)

A narrow `minimum_duration` rule is now available in a versioned **sidecar**, not in the strict scenario `2.0` JSON. The sidecar lives at `aggregate_requirements/<scenario_id>.json`, has `schema_version: "1.0"`, `scenario_id`, `scenario_sha256_canonical`, and a nonempty `requirements` array. Each rule has `id`, `kind: "minimum_duration"`, `event_category`, offset-aware `start`/`end`, positive `minimum_minutes`, and `complete_horizon`. The SHA binds a rule to the exact canonical scenario. Importing a scenario copies its sidecar. Historical scenarios without a sidecar retain their old behavior.

The simulator evaluates the **final** calendar after all operations, clips category-matching events to the explicit window, and counts the union of elapsed UTC intervals so overlapping blocks do not count twice. It reports `pass`, `fail`, or `unknown`; `unknown` blocks technical acceptance. A partial horizon is `unknown`. If a shortfall might be covered by an added event without a declared category, the result is `unknown`, not a false failure or success. Added events may now carry optional `category`, `importance`, and `participants`; old proposals remain readable and use neutral preview defaults. These checks certify only **scheduled duration**, not completed work or the external availability of a venue or person. Fixed events and other typed protections remain separate and unchanged.

Only two scenarios were migrated after checking an explicit 32-hour, five-weekday target and a represented Monday–Friday window: `freelancer_flexible_medical_appointment_birthday_dinner_001` (`weekly_hours`) and `freelancer_flexible_client_meeting_gaming_tournament_001` (`weekly_project_hours`). Their broad category rules were replaced by sidecars; all other individual protections remain. The latter still has a separate category protection involving flexible events, so its protection review is **not** fully resolved. The remaining duration, frequency, deadline, sleep and external-confirmation cases remain pending. No generic optimizer, proof of task completion, or autonomy rule was introduced. Candidate data and statuses are in `scenarios_candidate/`, `scenario_phase5_status.csv`, and the phase-5 section of `scenario_audit.md`.

## Phase 6 outcome (2026-11-20)

The existing `minimum_duration` implementation was reused without changing scenario schema `2.0`. The current `scenarios/` candidate contains **20** aggregate sidecars: ten freelancer five-weekday totals (including the two from phase 5) and ten nurse daily thesis cases. Each nursing rule covers one explicitly represented local calendar day, not an unseen week. Five daily rules can therefore coexist in one scenario. The hackathon freelancer's fixed client stand-ups were reclassified as `meeting` and protected by ID so they cannot be double-counted as solo client development. A proposal that adds work must declare a supported category; unknown metadata cannot silently satisfy the target. These checks prove reserved calendar time only.

A separate SHA-bound `confirmed_changes` sidecar now represents exact externally confirmed exceptions for protected events; it does not weaken the duration rule or fixed autonomy policy. Eight scenarios use it. The remaining completion, deadline, frequency and external-availability issues are tracked as real blockers or explicit uncertainties in `scenario_final_status.csv`; no weak aggregate proxy was presented as proof of completion. The simulator, runners, replay, import and gate export use the same sidecars. See `scenario_audit.md` phase 6 and `scenario_phase6_changes.csv` for the exact data changes.
