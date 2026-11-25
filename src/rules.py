"""Regras fixas de autonomia (baseline das configurações A e B).

Devolve ('act' | 'defer', [razões]). É propositadamente simples: é o termo de
comparação que o gate aprendido (configuração C) tem de superar.
"""
from __future__ import annotations

from models import Proposal
from scenario_v2 import V2Event

SENSITIVE_CATEGORIES = {"health", "supervisor_meeting", "social"}
IMPORTANCE_THRESHOLD = 4
MAX_CHANGES = 2


def rule_based_decision(
    proposal: Proposal, calendar: list[V2Event], violations: list[str]
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    by_id = {e.id: e for e in calendar}

    if violations:
        reasons.append("viola restrições rígidas ou referências inválidas")
    if not proposal.changes:
        reasons.append("sem mudanças concretas (pedido pode precisar de clarificação)")
    if len(proposal.changes) > MAX_CHANGES:
        reasons.append(f"mais de {MAX_CHANGES} mudanças")
    for c in proposal.changes:
        if c.type == "delete":
            reasons.append(f"apaga evento ({c.event_id})")
        e = by_id.get(c.event_id or "")
        if e is None:
            continue
        if e.importance >= IMPORTANCE_THRESHOLD:
            reasons.append(f"toca em evento importante ({e.id}, importância {e.importance})")
        if e.category in SENSITIVE_CATEGORIES:
            reasons.append(f"toca em categoria sensível ({e.category})")

    return ("defer" if reasons else "act"), reasons
