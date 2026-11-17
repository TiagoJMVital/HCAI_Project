# Experimental design and evidence boundaries

> **Schema v2 methodological update:** The gate label belongs to an adjudicated **concrete final B proposal**. Advance scenario annotation is no longer required. Authors judge scheduling acceptability first; only acceptable proposals receive `act/defer`. The exporter records exclusions for technical failures, below-threshold B outputs, missing consensus and quality rejections. Number of scenarios is therefore not the number of eligible gate examples. Critic rationale scores remain separate from scheduling quality and autonomy. Any instruction below to annotate scenarios first describes the archived workflow. Legacy A/B logic is intact. `eval/run_config_a_v2.py` and `eval/run_config_b_v2.py` share the same v2 Proposer adapter, technical validator and fixed autonomy rules; a controlled paired repetition plan and sufficient v2 corpus are still required before scientific A/B claims.

## Research comparisons from the proposal

The [Project Proposal](../../HCAI_Project_Proposal.pdf), §§4–5, proposes an ablation: **A vs B** isolates the added Critic and revision loop; **B vs C** isolates replacing fixed autonomy rules with a learned Learning-to-Defer gate, with the same Proposer–Critic process. A is one Proposer proposal plus fixed rules; B adds critique/revision then uses those same rules; C is future work. The planned hypotheses concern scheduling quality, rationale quality and calibrated autonomy. A higher Critic score alone establishes none of these.

For valid comparisons, use the same scenario inputs, profile, Proposer provider/model, prompts, fixed rules, quality rubric and evaluation timing. Record the Critic provider/model and generation settings as well. `--experiment-id` and `--repeat-index` on A/B runners group intended pairs, while each invocation receives a fresh `run_id`. `eval/compare_runs.py` checks whether paired records have matching Proposer provider/model; it does not compute scientific effects. Keep technical errors separate from legitimate `defer` outcomes. Do not silently remove failed runs.

## Outcome domains and planned measures

| Domain | Unit and proposed measurement | Implementation today |
| --- | --- | --- |
| Structural validity | Pydantic proposal/change fields | Implemented; regression tests |
| Operational applicability and hard constraints | In-memory change application and `find_violations`; rate of compliant proposals | Partial checks; no full constraint engine |
| Request satisfaction / scheduling quality | Human `scheduling_acceptable=yes/no` on a concrete proposal, supplemented by defensible objective checks; multiple schedules may be acceptable | v2 review field implemented; no real human reference; partial legacy objective checks for five scenarios |
| Rationale quality | Independent human rubric: coherence, clarity, trade-off justification, alternatives; compare initial/final B rationale | Critic score and history recorded; human rubric not yet applied |
| Critic refinement | Four dimension scores, overall score, revisions to threshold, failure rate, stratified by difficulty | Recorded for B; only isolated real run, no aggregate study |
| Autonomy | Against adjudicated proposal-level labels: defer precision, recall, F1, deferral rate and unsafe autonomy rate | Labels and C absent; fixed-rule decisions recorded |

Define the positive class as `defer`. The proposal defines unsafe autonomy rate as the proportion of cases **requiring confirmation** on which the system acts autonomously; specify its denominator and treatment of invalid/error cases before analysis. Report both false autonomous actions and unnecessary deferrals. Do not combine structural failures, Critic rejection and human-confirmation deferrals into one success category. A/B results are comparable only when the underlying proposal and metric domain are explicit; B may alter the proposal as well as its rationale.

The proposal's Table 1 expected behaviors and Figures 2–3 are **illustrative targets**, not experimental findings or annotations. Existing `eval/results/A/` records and the local A/B `soft_gym_01` runs demonstrate execution only. Those A and B runs generated different proposals and are not controlled paired repetitions; the B run had one revision and reached a Critic score of 4.0, but this cannot demonstrate a general improvement.

## Human assessment and repetitions

Two authors should review each final B proposal independently: record scheduling acceptability first and `act/defer` only for acceptable proposals, then adjudicate. There is no required advance scenario annotation in v2. For rationale quality, define and freeze a separate human rubric before assessing initial versus final B rationales; keep it distinct from Critic scoring and autonomy labelling. The current v2 review UI shows Critic scores/iterations as requested, which may bias human judgments; record that limitation or run a separately designed blinded assessment. An initial/final comparison may reveal textual clues even with masking.

The proposal does not fix a number of LLM repetitions, confidence interval method, or random seed policy. Recommended decision before data collection: choose a feasible, predeclared number of repeated runs per scenario and configuration, with paired `experiment_id`/`repeat_index`, a fixed provider/channel and the generation parameters actually exposed by that provider. Since IAedu may not expose temperature or seed control through this protocol, record that fact rather than claim determinism. Preserve all outputs and failures, report dispersion at the family and scenario levels, and avoid treating many near-identical variants as independent observations.

## Train/test discipline

Three families are reserved for training/development and three for final test. Tune features, gate thresholds, policy wording and model selection using training families only. Multiple proposals for one base remain in its group. Training-fold cross-validation is prepared, but only three training families make estimates fragile. Freeze the label protocol, feature extractor, classifier, threshold and analysis plan before unlocking test labels. If the benchmark needs expansion after viewing test results, create a new version and keep the original evaluation distinct.

## Remaining prerequisites for a valid study

1. Agree on the draft autonomy policy and run the training-only annotation pilot.
2. Collect enough accepted B proposals from training families with a predeclared sampling rule; preserve rejected/error runs separately for pipeline analysis. Decide whether and when to annotate A proposals for an independent A/B autonomy comparison, because the current gate catalog imports only accepted B proposals.
3. Complete independent **proposal** reviews and adjudication; inspect quality rejections, agreement and class diversity **on training data**. No advance scenario forms are required.
4. Expand objective request checks where defensible, and implement the human scheduling/rationale rubrics. A pass on five partial checks is not full scheduling validity.
5. Freeze a realistic, repeated A/B/C evaluation plan. Implement and train C using train families only, then evaluate held-out families once, with uncertainty and error analysis.
6. Decide whether the originally proposed Google Calendar and n8n components are required for the final demonstrator. Any use of private calendars needs a separate consent and privacy protocol.

No result currently supports a scientific conclusion that B improves A or that a learned gate improves fixed rules.
