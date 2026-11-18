# Draft autonomy policy for author discussion

> **Current schema v2 clarification:** Annotators first record `scheduling_acceptable=yes/no`. A `no` is a quality rejection with **no** autonomy label. Only `yes` proceeds to `act/defer`; the five defer reasons remain explanatory metadata, never predictive features. Advance scenario annotation is not part of the active workflow. The examples below remain hypotheses for discussion, never ground truth.

**Status: discussion draft.** The following rules and examples are hypotheses to help two authors agree on annotation criteria. They are **not** human labels, a trained gate, or a change to `src/rules.py`. The proposal's central question is whether a **specific valid proposal** may be acted on autonomously. Event topic alone should not determine the answer.

## Decision order

1. **Validity gate:** First check structure, event references, times, fixed commitments, permitted hours and applicability. If a proposal is invalid or cannot satisfy any acceptable outcome, reject/correct it or mark it unsafe for action. Human confirmation does not make an impossible change valid. The present validator covers only part of this gate; annotators must record uncovered issues.
2. **Critic gate in B/C:** A proposal below the Critic acceptance threshold is deferred by the pipeline and is not a gate-training example under the current catalog. A high score establishes only the Critic's assessment of visible reasoning, not calendar safety.
3. **Human autonomy judgement for a valid proposal:** Decide `act` only if the action is sufficiently specified, low enough in consequence, reversible where relevant, and authorized by explicit user preferences or a clear request. Decide `defer` if the user must choose among meaningful trade-offs or if impact/uncertainty/third-party effects exceed agreed bounds. State what extra confirmation would resolve it.

## Defer Reasons and Clarification Requirements

A `defer` decision indicates that a valid proposal should not be executed without further human involvement. However, not all deferments have the same underlying cause.

To support consistent human annotation and future analysis of the Learning-to-Defer system, annotators should identify one or more reasons for deferring a proposal.

| Reason | Description | Example |
|---|---|---|
| `clarification_required` | Essential information is missing or the user's request is insufficiently specified. | The user requests clearing a morning but does not explain whether missing a fixed class is acceptable. |
| `confirmation_required` | The proposed changes are valid but require explicit user approval. | Rescheduling an important personal appointment. |
| `high_impact` | The proposal has significant consequences or is difficult to reverse. | Cancelling a prepaid commitment or substantially reorganizing the week. |
| `third_party_impact` | The proposal affects other people, shared commitments or external arrangements. | Moving a meeting involving multiple participants. |
| `preference_conflict` | The proposal involves a meaningful trade-off between user preferences without sufficient prior authorization. | Cancelling a preferred gym session to create additional study time. |

### Annotation principles

- Multiple defer reasons may apply to the same proposal.
- Annotators should identify the primary reason and optionally additional reasons.
- These reasons are explanatory metadata, not separate prediction classes.
- The Learning-to-Defer gate retains the binary `act/defer` objective defined in the project proposal.
- A missing piece of information should only trigger `clarification_required` when it could materially affect the decision.
- A request for clarification should preferably identify the specific information needed, rather than asking several generic questions.
- Invalid proposals must be rejected or corrected through the validation process and must not be treated as ordinary valid-proposal deferments.
- Annotators must not infer defer reasons from the Critic score or the baseline rule-based decision.

### Clarification versus confirmation

Clarification and confirmation serve different purposes:

**Clarification:** The assistant lacks information needed to determine an appropriate action.

**Confirmation:** The assistant has enough information to formulate a valid proposal but should not execute it without explicit authorization.

Both result in `defer`, but they should be distinguished during annotation and subsequent qualitative evaluation.

### Scope of the current implementation

These categories are now explanatory fields in versioned proposal annotation forms, with a mandatory primary reason for completed `defer` forms. Historical forms remain in the local archive. They do not imply that the current system supports interactive clarification dialogues, and they are excluded from predictive gate features.

The implementation of follow-up questions, if adopted, should remain compatible with the original A/B/C experimental design and should not introduce additional prediction classes without a documented methodological justification.

## Factors to discuss and record

| Factor | Lower-autonomy concern | Possible support for `act` |
| --- | --- | --- |
| Importance of affected events | High importance or fixed commitment | Low-importance flexible event |
| Impact and number/type of changes | Deletion, paid booking, many cascading moves | One small move or addition with no loss |
| Ambiguity | Vague goal, missing priority or duration | Exact request and unambiguous target |
| Reversibility | Cancellation fee, lost slot, missed deadline | Easily undone before anyone is affected |
| Explicit preference | Unknown or conflicting preference | Clear prior authorization for this kind of move |
| Third parties | Attendance, notification, shared reservation or agreement | Private event with no external dependency |
| Hard constraints | Any violation | All known hard constraints satisfied, with residual uncertainty noted |

Importance and impact are not interchangeable: a low-importance event may still affect someone else, and a health-related entry may be a harmless private reminder. The number of changes is a signal, not a sufficient verdict. A user can explicitly authorize some action types while withholding others. Discuss whether explicit authorization can ever override a default `defer` for high-impact changes; it cannot override hard constraints.

## Illustrative Act/Defer matrix

Every row is a **hypothetical pair of valid proposals**. They are not labels for the current benchmark. Confirm that timing and hard constraints are satisfied before applying either example.

| Theme | Possible `act` hypothesis | Possible `defer` hypothesis |
| --- | --- | --- |
| Academic commitments | Add a private 45-minute study block in a free slot explicitly requested by the student. | Move an important lab preparation block close to a deadline when the student did not prioritize competing work. |
| Gym and personal habits | Move a flexible solo workout to an equivalent free slot under a standing preference. | Cancel a prepaid class or move a session promised to a training partner. |
| Health | Add a private medication reminder at the exact time the user explicitly specified. | Reschedule a clinical appointment or infer a new medical priority from a vague request. |
| Social commitments | Add a personal reminder to call a friend at the user's specified time. | Move a shared dinner reservation or cancel attendance without the other person's agreement. |
| Meetings with third parties | Add a private preparation block before a confirmed meeting. | Move the meeting itself or send invitations to participants without permission. |
| Travel and transport | Add private packing time around a fixed journey with ample margin. | Change a booked journey or move a transfer that risks a missed connection. |
| Deadlines and rest | Add a short focus block before a deadline while preserving a protected break. | Remove sleep/rest time or displace an important task based on an unspecified urgency judgement. |

The same theme can yield either decision because the **actual proposal**, its context and consequences matter. A structurally invalid version of any example belongs in the validity gate, not in the table's valid-proposal `defer` category.

## Dataset balance without artificial quotas

Training needs examples of both `act` and `defer` to estimate a boundary and expose errors. After independent training-family annotation, inspect whether one class is absent or tied to a single category; if so, collect additional **training-family** proposals through a predeclared, documented procedure. Do not invent labels or force a 50/50 split. Artificial balancing can make a model seem calibrated for a world unlike its intended use. Preserve a realistic class distribution in held-out evaluation and report prevalence, deferral rate, unsafe autonomy and uncertainty. If training sampling deliberately changes prevalence, disclose it and do not apply that prevalence to test metrics without care.

## Pilot discussion checklist

Use a small, preselected set of training-family proposals as described in [Annotation protocol](04_ANNOTATION_PROTOCOL.md). Ask each author to write the reason for `act/defer` **for each concrete proposal**, identify any invalid proposal separately, and mark what additional user information would change the judgement. Compare independently completed forms, review disagreements and refine the definitions before formal labelling. Do not alter test families or fixed baseline rules based on this pilot.
