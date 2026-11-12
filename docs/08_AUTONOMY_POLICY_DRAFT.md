# Draft autonomy policy for author discussion

**Status: discussion draft.** The following rules and examples are hypotheses to help two authors agree on annotation criteria. They are **not** human labels, a trained gate, or a change to `src/rules.py`. The proposal's central question is whether a **specific valid proposal** may be acted on autonomously. Event topic alone should not determine the answer.

## Decision order

1. **Validity gate:** First check structure, event references, times, fixed commitments, permitted hours and applicability. If a proposal is invalid or cannot satisfy any acceptable outcome, reject/correct it or mark it unsafe for action. Human confirmation does not make an impossible change valid. The present validator covers only part of this gate; annotators must record uncovered issues.
2. **Critic gate in B/C:** A proposal below the Critic acceptance threshold is deferred by the pipeline and is not a gate-training example under the current catalog. A high score establishes only the Critic's assessment of visible reasoning, not calendar safety.
3. **Human autonomy judgement for a valid proposal:** Decide `act` only if the action is sufficiently specified, low enough in consequence, reversible where relevant, and authorized by explicit user preferences or a clear request. Decide `defer` if the user must choose among meaningful trade-offs or if impact/uncertainty/third-party effects exceed agreed bounds. State what extra confirmation would resolve it.

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

Use the six suggested training scenarios in [Annotation protocol](04_ANNOTATION_PROTOCOL.md#small-annotation-pilot-before-formal-collection). Ask each author to write the reason for `act/defer` **for each concrete proposal**, identify any invalid proposal separately, and mark what additional user information would change the judgement. Compare independently completed forms, review disagreements and refine the definitions before formal labelling. Do not alter test families or fixed baseline rules based on this pilot.
