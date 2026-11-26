# Project overview

## Research question

Can a human-centred calendar assistant produce useful scheduling proposals while choosing appropriately between autonomous action and human confirmation? The [Project Proposal](../../HCAI_Project_Proposal.pdf) specifies a Proposer, an independent Critic and a Learning-to-Defer gate. The project currently operates on synthetic calendars and never writes to Google Calendar.

## Experimental configurations

| Configuration | Pipeline | Current state |
| --- | --- | --- |
| A | Proposer → deterministic validation → fixed autonomy rules | Implemented and tested with mocked providers; isolated historical live run exists |
| B | Same Proposer → validation → independent Critic → up to three revisions → same fixed rules | Implemented and tested with mocked providers; one imported B proposal exists |
| C | Proposer + Critic → learned Act/Defer gate | Planned, not implemented or trained |

B defers if the Critic never accepts. Neither Critic approval nor an LLM's text replaces deterministic safety checks. An `act` is a simulated decision, not an external calendar mutation. IAedu GPT-5.5 is the configured provider; Ollama remains an alternative. The code supports independent provider/model configuration for the two agents. See [architecture](02_ARCHITECTURE.md).

The Critic now sees the complete calendar derived by applying each proposal virtually, as well as the operations, rationale and limited validation report. This extends B's assessment from textual coherence to practical scheduling plausibility without exposing the original request or full profile. The Critic does not impose generic transition, commute, meal or sleep constraints. A's Proposer prompt, validator and fixed autonomy rules are unchanged; C remains future work.

## Current methodological decision

The active benchmark uses standalone schema `2.0` scenarios with a complete profile, calendar and request. Human reviewers judge **final concrete B proposals** directly: scheduling acceptability first, then `act/defer` if acceptable. This replaces advance scenario annotation. The choice matches the future gate's decision unit: actual proposed changes and a Critic score can vary between proposals for the same request. The scenario JSON itself contains no human label or expected schedule. Independent author reviews and adjudication remain mandatory. See [annotation protocol](04_ANNOTATION_PROTOCOL.md).

The active corpus currently holds one imported scenario (`working_student_deadline_001`), one B proposal and one `author_a` draft. The former 20-base/41-variant benchmark and its data/results are in a SHA-256-verified local archive, excluded from the active benchmark and new commits. See [cleanup record](09_CLEANUP_PLAN.md). No broad A/B comparison, human label study or C result has yet been produced. Historical isolated runs are engineering checks, not scientific conclusions.

## Pending work

Build a diverse v2 benchmark across profiles and scenario families; generate paired A/B runs with a frozen protocol; finish independent proposal reviews and adjudication; evaluate scheduling, rationale and autonomy separately; freeze the gate's features/policy; train and evaluate C without using held-out families for development. External calendar, n8n and real-world deployment remain outside the current implementation.
