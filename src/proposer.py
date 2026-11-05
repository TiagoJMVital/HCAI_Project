"""Proposer: gera proposta de calendário + justificação explícita."""
from __future__ import annotations

from llm import DEFAULT_MODEL, generate_structured
from models import CalendarEvent, Profile, Proposal, Scenario

SYSTEM = """You are a personal calendar assistant. Given the user's request, their
calendar and their preference profile, propose concrete calendar changes and
explain your reasoning.

Rules:
- NEVER move, delete or overlap events marked fixed=true.
- Only use event_id values that exist in the calendar (for add, invent a new id).
- Use ISO 8601 times without timezone, e.g. 2026-11-11T18:00.
- Respect no_events_before / no_events_after and keep weekends free.
- Prefer the smallest set of changes that satisfies the request.
- If a flexible, low-priority commitment conflicts with a higher-priority one,
  move the lower-priority one and say why.
- The rationale must list the relevant constraints, the priorities that decided
  the trade-off, and at least one alternative you considered and rejected.
- If the request is ambiguous, still propose the most plausible change and say
  in the rationale what is uncertain.
Answer ONLY with JSON matching the schema."""


def _fmt_event(e: CalendarEvent) -> str:
    flag = " [FIXED]" if e.fixed else ""
    return (f"- id={e.id} | {e.title} | {e.start} -> {e.end} | "
            f"category={e.category} | importance={e.importance}{flag}")


def build_prompt(profile: Profile, scenario: Scenario) -> str:
    prio = ", ".join(f"{p.category}={p.weight}" for p in profile.priorities)
    flex = "; ".join(
        f"{f.title} ({'/'.join(f.days)} {f.start}, {f.duration_min} min, "
        f"{'movable' if f.movable else 'not movable'})"
        for f in profile.flexible_commitments
    )
    cal = "\n".join(_fmt_event(e) for e in sorted(scenario.calendar, key=lambda e: e.start))
    return (
        f"Current time: {scenario.now}\n\n"
        f"PRIORITIES (1-5, higher wins): {prio}\n"
        f"FLEXIBLE COMMITMENTS: {flex}\n"
        f"PREFERENCES: no events before {profile.preferences.no_events_before}, "
        f"none after {profile.preferences.no_events_after}, "
        f"weekends protected={profile.preferences.protect_weekend}\n\n"
        f"CALENDAR:\n{cal}\n\n"
        f"USER REQUEST: {scenario.user_request}"
    )


def propose(profile: Profile, scenario: Scenario, *, model: str = DEFAULT_MODEL,
            feedback: str | None = None, previous: Proposal | None = None) -> Proposal:
    """Gera uma proposta. `feedback`/`previous` serão usados pelo Critic (passo 5)."""
    prompt = build_prompt(profile, scenario)
    if feedback and previous:
        prompt += (
            f"\n\nYOUR PREVIOUS PROPOSAL:\n{previous.model_dump_json(indent=1)}\n\n"
            f"REVIEWER FEEDBACK:\n{feedback}\n\nRevise the proposal and rationale."
        )
    return generate_structured(prompt, Proposal, system=SYSTEM, model=model)
