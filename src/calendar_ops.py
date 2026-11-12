"""Aplicar mudanças a um calendário simulado e verificar restrições rígidas."""
from __future__ import annotations

from datetime import datetime, timedelta

from models import CalendarEvent, Change, Profile, Proposal

DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _fmt(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M")


def apply_changes(calendar: list[CalendarEvent], changes: list[Change]) -> list[CalendarEvent]:
    """Devolve uma cópia do calendário com as mudanças aplicadas."""
    events = {e.id: e.model_copy() for e in calendar}
    for i, c in enumerate(changes):
        if c.type == "delete" and c.event_id in events:
            del events[c.event_id]
        elif c.type == "move" and c.event_id in events and c.to_start:
            e = events[c.event_id]
            dur = _dt(e.end) - _dt(e.start)
            start = _dt(c.to_start)
            end = _dt(c.to_end) if c.to_end else start + dur
            e.start, e.end = _fmt(start), _fmt(end)
        elif c.type == "add" and c.to_start:
            start = _dt(c.to_start)
            end = _dt(c.to_end) if c.to_end else start + timedelta(hours=1)
            eid = c.event_id or f"new_{i}"
            events[eid] = CalendarEvent(
                id=eid, title=c.title or "New event",
                start=_fmt(start), end=_fmt(end),
            )
    return list(events.values())


def _overlap(a: CalendarEvent, b: CalendarEvent) -> bool:
    return _dt(a.start) < _dt(b.end) and _dt(b.start) < _dt(a.end)


def find_violations(
    original: list[CalendarEvent], proposal: Proposal, profile: Profile
) -> list[str]:
    """Violações de restrições rígidas e referências inválidas.

    Verifica: eventos fixos apagados/movidos, event_id inexistente, datas
    inválidas, sobreposição com eventos fixos e horários fora da janela
    permitida pelas preferências.
    """
    problems: list[str] = []
    by_id = {e.id: e for e in original}
    added_ids: set[str] = set()

    for i, c in enumerate(proposal.changes):
        if c.type == "add":
            added_id = c.event_id or f"new_{i}"
            if added_id in by_id or added_id in added_ids:
                problems.append(f"event_id já existe: {added_id}")
            added_ids.add(added_id)
        if c.type in ("move", "delete") and c.event_id not in by_id:
            problems.append(f"event_id inexistente: {c.event_id}")
        elif c.type in ("move", "delete") and by_id[c.event_id].fixed:
            problems.append(f"altera evento fixo: {c.event_id}")
        for field in (c.to_start, c.to_end):
            if field:
                try:
                    _dt(field)
                except ValueError:
                    problems.append(f"data inválida: {field}")
        if c.to_start and c.to_end:
            try:
                if _dt(c.to_end) <= _dt(c.to_start):
                    problems.append(f"duração não positiva: {c.event_id or c.title}")
            except ValueError:
                pass
    if problems:
        return problems  # não faz sentido simular com dados inválidos

    after = apply_changes(original, proposal.changes)
    if proposal.changes and {e.id: e.model_dump() for e in after} == {
        e.id: e.model_dump() for e in original
    }:
        problems.append("sem alteração efetiva")
    fixed_ids = {e.id for e in original if e.fixed}
    touched = {c.event_id for c in proposal.changes if c.event_id} | {
        e.id for e in after if e.id not in by_id
    }

    lo = datetime.strptime(profile.preferences.no_events_before, "%H:%M").time()
    hi = datetime.strptime(profile.preferences.no_events_after, "%H:%M").time()
    for e in after:
        if e.id not in touched:
            continue
        s, en = _dt(e.start), _dt(e.end)
        if s.time() < lo or en.time() > hi or s.date() != en.date():
            problems.append(f"fora do horário permitido: {e.id} ({e.start}-{e.end})")
        if profile.preferences.protect_weekend and s.weekday() >= 5:
            problems.append(f"fim de semana protegido: {e.id}")
        for f in after:
            if f.id != e.id and f.id in fixed_ids and _overlap(e, f):
                problems.append(f"sobrepõe evento fixo: {e.id} x {f.id}")
    return problems
