# Direct proposal annotation

The decision unit is a final **concrete B proposal**. No advance scenario review is required. The scenario contains original request, profile, time and synthetic calendar; the proposal artifact in `data/proposals/` contains final changes, rationale, Critic iterations and technical validation. The original draft proposal and run history remain in the result/artifact for audit. See [ANNOTATION.md](../ANNOTATION.md) for commands and UI steps.

For new B runs, each Critic iteration also records the complete calendar obtained by deterministic simulation. The Critic receives that result calendar, proposal, rationale, timezone and limited technical report, while the original request and full profile remain outside its input. Historical imported artifacts lack this optional record and stay readable. Plausibility feedback does not establish request satisfaction or a human autonomy label.

With Critic policy `plausibility_review_v1`, new iterations additionally store an explicit, validated plausibility revision decision and the numeric/combined acceptance outcome. Historical iterations without this review display “not available” in Streamlit. Authors must not treat Critic acceptance, requested revision, severity or score as a human autonomy label. A revision does not guarantee improved scheduling; judge the final concrete proposal directly and preserve earlier iterations for later analysis.

Runs using `uncertainty_review_v2` also store structured, unverified conditions per iteration and on the final evaluation. These are Critic observations, not verified facts, technical failures or autonomy labels. A final empty list means the Critic identified none; historical absence means no structured assessment was made. Earlier conditions remain visible in the history even when the final response omits them; the UI does not automatically mark them resolved. `proposal_ready` means the Critic accepted quality under its policy, not that external resources are confirmed or that human authorization is unnecessary. The existing annotation form and gate export remain unchanged.

Current B iteration history records whether operations or rationale changed after a quality-control request. The Proposer may keep the same schedule with a reasoned explanation; the next Critic review should address its earlier concern. Annotators still judge the final proposal independently of whether this exchange occurred or how many iterations it took.

## Two independent evaluations

Both `author_a` and `author_b` see the same scenario and final proposal in Streamlit, including technical validation and Critic history. Each works in a separate JSON form in `data/annotations/<author>/<proposal_id>.json`; the UI hides the other form until both are complete. The author selector is not authentication. Each records `scheduling_acceptable` (`yes`/`no`), a primary reason, optional additional defer reasons, and a free-text justification. An acceptable proposal requires `autonomy_decision` (`act`/`defer`); an unacceptable one has no autonomy label. The five defer reasons are `clarification_required`, `confirmation_required`, `high_impact`, `third_party_impact`, and `preference_conflict`. An `act` reason is free text. Drafts may be incomplete; completion applies Pydantic validation. Invalid technical proposals are quality rejections, not forced `defer`s.

The policy examples in [08_AUTONOMY_POLICY_DRAFT.md](08_AUTONOMY_POLICY_DRAFT.md) are provisional and never automatic labels. Reviewers should separate whether the scheduling would satisfy the request from whether the assistant may autonomously enact it. Critic scores shown in the UI may bias these judgments; the evaluation protocol must record or control this limitation.

## Comparison and adjudication

After both forms are complete, `src/annotation_v2.py` compares acceptability, autonomy and reasons, computes observed autonomy agreement and Cohen's kappa where defined. The authors resolve disagreements manually and record a named adjudicator, consensus justification and disagreement fields. The consensus in `data/annotations/adjudicated/<proposal_id>.json` retains hashes of both original forms; it does not overwrite them. A changed review makes the stored consensus stale. Small or one-class samples make kappa unstable or undefined.

## Gate export

`python src/gate_dataset_v2.py --split train` exports only applicable, Critic-accepted, technically valid, human-accepted and adjudicated proposals to `data/gate_datasets/train.jsonl`, with an exclusions report. The label is the consensus `act/defer`. Human reasons, justifications and scenario/profile/family identifiers remain metadata, not predictors. The test split stays locked until the model and policy are frozen. Number of scenarios is not the number of eligible examples. No training happens during export.
