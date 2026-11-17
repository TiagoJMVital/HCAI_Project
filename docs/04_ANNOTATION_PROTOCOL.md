# Direct proposal annotation protocol (schema v2)

The current unit of annotation is one **final B proposal**, not the abstract scenario. The research question is whether a technically applicable and acceptable *concrete* scheduling proposal may be performed autonomously. A scenario annotation is no longer a prerequisite. This is a deliberate methodological change from the earlier two-stage implementation; it avoids assigning an `act/defer` label before the actual proposed changes, justification and Critic assessment exist. The source scenario remains independent and contains no human labels, expected schedule or autonomy decision.

The operational instructions and exact commands are in [ANNOTATION.md](../ANNOTATION.md). The old two-stage code, forms and results remain available under their original paths. No historical form is overwritten or silently converted.

## Material shown to each author

Both `author_a` and `author_b` see the *same* imported proposal and original scenario: request, full profile, calendar, final changes and Proposer rationale. The v2 UI additionally shows the deterministic validation report and Critic scores/iterations, as required for this protocol. This differs from the earlier blinded packet, which hid Critic information. Authors should avoid interpreting the Critic's score as proof of scheduling quality. Model/provider identifiers, B's fixed-rule decision, preliminary legacy labels, split and the other author's response are not shown on the v2 review page. The consensus page reveals independent responses only after both are complete. The author selector is not access control.

The calendar is read-only and starts in a week derived from the scenario date. An original/proposed toggle appears only if the proposal can be simulated safely. It marks created, moved and removed blocks while preserving fixed/flexible text. An identified requested interval is shown only when the existing deterministic parser can establish it; otherwise the request text remains visible without a guessed interval. The proposed calendar is a simulation, never a real calendar write.

## Independent form and completion criteria

`data/annotation_work_v2/<author>/<proposal_id>.json` stores `scheduling_acceptable` (`yes`/`no`), `autonomy_decision` (`act`/`defer` only for acceptable scheduling), `primary_reason`, optional `additional_reasons`, `justification` and `status`. A draft can be incomplete. A complete form requires acceptability, a primary reason and a written justification. If scheduling is unacceptable, the autonomy field **must be empty**. This records quality rejection without fabricating a `defer` gate label. If scheduling is acceptable, choose `act` or `defer`. For `defer`, the primary reason is one of the five reasons in [the autonomy policy draft](08_AUTONOMY_POLICY_DRAFT.md). For `act`, explain the main reason in free text; a defer reason is not required.

Technical validity is separate: `src/calendar_v2.py` checks the typed rules it implements and reports unverified aspects. A technical failure blocks proposed-calendar preview and gate export. An annotator may record a quality rejection for analysis, but a technically invalid proposal is not an ordinary autonomy example. The machine's status is not a human label.

## Comparison and adjudication

The pair is visible only after both forms are complete. `src/annotation_v2.py` computes field disagreements, observed agreement for paired autonomy decisions and Cohen's kappa where defined. The authors discuss scheduling acceptability first, then autonomy and rationale. They fill a separate consensus record with the agreed fields, disagreement list, named adjudicator and hashes of both original reviews. No decision is copied automatically. Original forms remain unchanged and become frozen after consensus completion. Completed forms and consensuses require explicit confirmation before modification; a changed file revision triggers a reload error.

Kappa is undefined without eligible paired decisions or when expected chance agreement is one. Report the denominator, class prevalence and quality rejections alongside kappa; a tiny pilot does not support strong reliability claims.

## Gate export and leakage control

`src/gate_dataset_v2.py` exports only technically valid, Critic-accepted B proposals with complete independent reviews and a completed *acceptable* consensus. The script records explicit exclusion reasons for everything else. Each eligible row has metadata IDs, family, profile and split, predictive features, Critic score and the adjudicated `act/defer` label. IDs, split, author reasons, justifications, decisions and consensus fields are **not features**. Multiple proposals for the same scenario remain in the same family. Training folds group by family; test export is blocked unless explicitly unlocked after the feature extractor, classifier and evaluation policy are frozen. The command exports rows only; no classifier is trained.

## Illustrative discussion examples — not data

- A private, reversible gym reschedule in a free slot could be `scheduling_acceptable=yes`, `act`, with a free-text reason about low impact. This is a hypothetical policy example, **not** an author annotation.
- A feasible move of a meeting involving another person could be `yes`, `defer`, primary reason `third_party_impact`. Again, this is only a discussion example.
- Moving a fixed work shift is technically invalid under the typed protection rule; do not label it a normal `defer` example. A human quality rejection may be recorded separately.

## Pilot and open decisions

Start a small pilot using training families or separate development cases, with a few *real generated* B proposals. Authors annotate independently, compare disagreements, revise the policy and freeze definitions before formal collection. Do not alter test-family scenarios or use test labels to tune the gate. Decide in advance how many proposals per scenario to sample, how to treat below-threshold Critic outputs in qualitative analysis, and whether seeing Critic scores might bias human autonomy judgments. The current v2 UI shows those scores because this protocol explicitly requests them; a future controlled study could add blinded conditions without changing stored labels retrospectively.
