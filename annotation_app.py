"""Local Streamlit interface for the existing two-stage HCAI annotation workflow."""
from __future__ import annotations

import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from annotation_ui import (  # noqa: E402
    AUTHORS, adjudication_progress, comparison, items, load_adjudication,
    load_item, load_pair, paired_ids, prepare, save_adjudication, save_form,
)
from annotation_workflow import DEFER_REASONS  # noqa: E402
from calendar_view import (  # noqa: E402
    identify_requested_interval, initial_week,
    overlap_summary, proposed_events, render_week_html, view_events,
    week_after,
)
from annotation_v2 import (  # noqa: E402
    DEFER_REASONS as V2_DEFER_REASONS, ProposalConsensus, ProposalReview,
    compare as compare_v2, load_consensus as load_consensus_v2,
    load_review as load_review_v2, pair as pair_v2,
    save_consensus as save_consensus_v2, save_review as save_review_v2,
)
from annotation_v2_ui import (preview as preview_v2, records as records_v2,
                              temporal_overlaps)  # noqa: E402
from proposal_catalog_v2 import catalog as catalog_v2  # noqa: E402
from scenario_v2 import load_scenario as load_scenario_v2  # noqa: E402

st.set_page_config(page_title="HCAI · Human annotation", page_icon="📅", layout="wide")

REASON_LABELS = {
    "clarification_required": "Clarificação necessária",
    "confirmation_required": "Confirmação necessária",
    "high_impact": "Impacto elevado",
    "third_party_impact": "Impacto em terceiros",
    "preference_conflict": "Conflito de preferências",
}
STATES = {"all": "Todos", "not_started": "Não iniciados", "draft": "Rascunhos",
          "complete": "Concluídos", "needs_correction": "Precisam de correção"}


def _list_editor(label: str, values: list[str], key: str) -> list[str]:
    st.caption("Acrescenta uma linha com + ou remove linhas no editor.")
    edited = st.data_editor(pd.DataFrame([{"Entrada": item} for item in values],
                                            columns=["Entrada"]),
                            num_rows="dynamic", hide_index=True, key=key,
                            width="stretch", column_config={
                                "Entrada": st.column_config.TextColumn(label, width="large")})
    if hasattr(edited, "to_dict"):
        rows = edited.to_dict("records")
    else:
        rows = edited
    return [str(row["Entrada"]).strip() for row in rows
            if row.get("Entrada") is not None and not pd.isna(row["Entrada"])
            and str(row["Entrada"]).strip()]


def _option(label: str, choices: list, value, key: str, format_func=str):
    return st.selectbox(label, choices, index=choices.index(value) if value in choices else 0,
                        format_func=format_func, key=key)


def _weekly_calendar(packet: dict, events: list, *, mode: str) -> None:
    interval = identify_requested_interval(packet)
    base_week = initial_week(packet, interval)
    offset_key = f"week:{packet['scenario_id']}:{mode}"
    st.session_state.setdefault(offset_key, 0)
    left, middle, right = st.columns([1, 2, 1])
    if left.button("← Semana anterior", key=offset_key + ":previous"):
        st.session_state[offset_key] -= 1
    if right.button("Semana seguinte →", key=offset_key + ":next"):
        st.session_state[offset_key] += 1
    week = week_after(base_week, st.session_state[offset_key])
    if middle.button(f"{week:%d/%m/%Y} – {(week + timedelta(days=6)):%d/%m/%Y} · voltar à semana inicial",
                     key=offset_key + ":reset"):
        st.session_state[offset_key] = 0
        week = base_week
    st.html(render_week_html(events, week, interval))
    st.caption("Cores: 🟥 académico/aulas · 🟦 ginásio · 🟩 saúde · 🟪 estudo · "
               "🩵 reuniões · 🟨 social · ⬜ viagens/outros. Cada bloco indica "
               "Fixo ou Flexível; o contorno assinala sobreposição com o pedido. "
               "Passe o cursor sobre um bloco ou abra a tabela para ver detalhes.")
    if mode == "proposed":
        st.caption("Traço grosso: adicionado ou movido. Contorno esbatido: removido ou posição "
                   "anterior, apenas como referência; não faz parte do calendário proposto.")
    if interval is None:
        st.info("Intervalo não identificado automaticamente. Consulte o pedido original; "
                "não foi inferida uma seleção temporal.")
    else:
        st.caption(f"Intervalo solicitado pelo utilizador: {interval.start:%d/%m/%Y %H:%M}–"
                   f"{interval.end:%d/%m/%Y %H:%M}. Faixa âmbar tracejada.")
        summary = overlap_summary(events, interval)
        st.write(f"**Sobreposição temporal:** {summary['total']} evento(s): "
                 f"{summary['fixed']} fixo(s) e {summary['flexible']} flexível(eis). "
                 "Sobreposição não é, por si só, uma violação de restrições rígidas.")


def _scenario_view(packet: dict, *, proposal_packet: dict | None = None) -> None:
    st.subheader(f"Cenário {packet['scenario_id']}")
    st.info(packet["user_request"])
    st.caption(f"Data e hora de referência: {packet['now']}")
    original = view_events(packet["calendar"])
    active, mode = original, "original"
    if proposal_packet is not None:
        preview, _problems = proposed_events(proposal_packet)
        if preview is None:
            st.warning("Pré-visualização do calendário proposto indisponível: as alterações "
                       "não passaram nas verificações estruturais e operacionais disponíveis. "
                       "A proposta final continua visível abaixo; nenhuma alteração foi apresentada como aplicada.")
        else:
            choice = st.radio("Vista do calendário", ("Calendário original", "Calendário proposto"),
                              horizontal=True, key=f"calendar:{packet['scenario_id']}:mode")
            if choice == "Calendário proposto":
                active, mode = preview, "proposed"
                st.caption("Pré-visualização em memória após as verificações determinísticas existentes. "
                           "Não demonstra satisfação integral do pedido nem altera qualquer calendário.")
    _weekly_calendar(packet, active, mode=mode)
    with st.expander("Ver eventos em tabela"):
        events = sorted(packet["calendar"], key=lambda e: e["start"])
        st.dataframe([{"Início": e["start"], "Fim": e["end"], "Evento": e["title"],
                       "Categoria": e["category"], "Importância": e["importance"],
                       "Estado": "Fixo" if e["fixed"] else "Flexível"} for e in events],
                     hide_index=True, width="stretch")
    profile = packet["profile"]
    left, right = st.columns(2)
    with left:
        st.markdown("#### Restrições rígidas do perfil")
        for entry in profile["hard_constraints"]:
            st.write(f"• {entry['title']} — {entry['recurrence']}")
        st.markdown("#### Preferências")
        prefs = profile["preferences"]
        st.write(f"Horário: {prefs['no_events_before']}–{prefs['no_events_after']}; "
                 f"fim de semana protegido: {'sim' if prefs['protect_weekend'] else 'não'}")
    with right:
        st.markdown("#### Prioridades")
        for priority in profile["priorities"]:
            st.write(f"• {priority['category']}: {priority['weight']}/5")
        st.markdown("#### Compromissos flexíveis")
        for entry in profile["flexible_commitments"]:
            st.write(f"• {entry['title']} — {', '.join(entry['days'])} "
                     f"{entry['start']} ({entry['duration_min']} min); "
                     f"movível: {'sim' if entry['movable'] else 'não'}")


def _reference_view(reference: dict) -> None:
    st.markdown("#### Consenso adjudicado do cenário")
    st.write("**Restrições:**", reference["hard_constraints"] or "Nenhuma registada")
    st.write("**Resultados aceitáveis:**", reference["acceptable_outcomes"])
    st.write("**Fatores de impacto:**", reference["impact_factors"] or "Nenhum registado")
    st.write("**Ambiguidade:**", "Sim" if reference["ambiguity_present"] else "Não")
    if reference["ambiguity_notes"]:
        st.write(reference["ambiguity_notes"])


def _proposal_view(packet: dict) -> None:
    _scenario_view(packet["scenario"], proposal_packet=packet)
    _reference_view(packet["scenario_reference"])
    proposal = packet["final_proposal"]
    st.markdown("#### Alterações propostas")
    for index, change in enumerate(proposal["changes"], 1):
        label = {"add": "Adicionar", "move": "Mover", "delete": "Eliminar"}[change["type"]]
        detail = change.get("title") or change.get("event_id") or "Evento"
        times = " → ".join(str(x) for x in (change.get("from_start"), change.get("to_start"),
                                             change.get("to_end")) if x)
        st.write(f"**{index}. {label}:** {detail}" + (f" · {times}" if times else ""))
    rationale = proposal["rationale"]
    st.markdown("#### Justificação do Proposer")
    st.write(rationale["summary"])
    st.write("**Restrições consideradas:**", rationale["constraints"] or "Nenhuma descrita")
    st.write("**Prioridades consideradas:**", rationale["priorities"] or "Nenhuma descrita")
    if rationale["alternatives_considered"]:
        st.write("**Alternativas:**")
        for alt in rationale["alternatives_considered"]:
            st.write(f"• {alt['option']} — rejeitada porque {alt['rejected_because']}")


def _scenario_fields(form: dict, prefix: str, *, adjudication: bool = False) -> dict:
    values = {
        "hard_constraints": _list_editor("Restrições rígidas relevantes", form["hard_constraints"], prefix + ":hard"),
        "acceptable_outcomes": _list_editor("Resultados de scheduling aceitáveis", form["acceptable_outcomes"], prefix + ":outcomes"),
        "impact_factors": _list_editor("Fatores de impacto", form["impact_factors"], prefix + ":impact"),
        "ambiguity_present": _option("O pedido tem ambiguidade relevante?", [None, True, False],
                                     form["ambiguity_present"], prefix + ":ambiguity",
                                     lambda x: "Por avaliar" if x is None else ("Sim" if x else "Não")),
        "ambiguity_notes": st.text_area("Notas sobre ambiguidade", value=form["ambiguity_notes"],
                                        key=prefix + ":ambiguity_notes"),
    }
    if adjudication:
        values["resolution_rationale"] = st.text_area(
            "Como resolveram os desacordos?", value=form["resolution_rationale"],
            key=prefix + ":resolution")
    return values


def _proposal_fields(form: dict, prefix: str, *, adjudication: bool = False) -> dict:
    key = "final_decision" if adjudication else "decision"
    decision = _option("Decisão de autonomia para esta proposta", [None, "act", "defer"],
                       form[key], prefix + ":decision",
                       lambda x: "Por decidir" if x is None else x.upper())
    acceptable = _option("O scheduling proposto é aceitável?", [None, True, False],
                         form["scheduling_acceptable"], prefix + ":acceptable",
                         lambda x: "Por avaliar" if x is None else ("Sim" if x else "Não"))
    if decision == "act" and acceptable is False:
        st.error("Uma proposta inaceitável não pode ser classificada como ACT.")
    values = {key: decision, "decision_rationale": st.text_area(
        "Justificação da decisão", value=form["decision_rationale"],
        key=prefix + ":decision_rationale"),
        "scheduling_acceptable": acceptable,
        "intervention_impact": _option("Impacto da intervenção (1–5)", [None, 1, 2, 3, 4, 5],
                                        form["intervention_impact"], prefix + ":impact_scale",
                                        lambda x: "Por avaliar" if x is None else str(x)),
        "intervention_risk": _option("Risco da intervenção (1–5)", [None, 1, 2, 3, 4, 5],
                                      form["intervention_risk"], prefix + ":risk_scale",
                                      lambda x: "Por avaliar" if x is None else str(x)),
        "risk_factors": _list_editor("Fatores de risco", form["risk_factors"], prefix + ":risks")}
    if not adjudication:
        values["ambiguity_notes"] = st.text_area("Notas de ambiguidade", value=form["ambiguity_notes"],
                                                   key=prefix + ":ambiguity_notes")
    if decision == "defer":
        values["defer_reason_primary"] = _option(
            "Motivo principal de deferimento *", [None, *DEFER_REASONS],
            form["defer_reason_primary"], prefix + ":defer_primary",
            lambda x: "Selecionar" if x is None else REASON_LABELS[x])
        values["defer_reason_additional"] = st.multiselect(
            "Motivos adicionais (opcionais)",
            [reason for reason in DEFER_REASONS if reason != values["defer_reason_primary"]],
            default=[reason for reason in form["defer_reason_additional"]
                     if reason != values["defer_reason_primary"]],
            format_func=lambda x: REASON_LABELS[x], key=prefix + ":defer_additional")
        if "clarification_required" in ({values["defer_reason_primary"]} |
                                        set(values["defer_reason_additional"])):
            values["clarification_question"] = st.text_area(
                "Pergunta específica de esclarecimento (opcional)",
                value=form["clarification_question"], key=prefix + ":question")
        else:
            values["clarification_question"] = ""
    else:
        values.update(defer_reason_primary=None, defer_reason_additional=[], clarification_question="")
    values["annotation_version"] = 2
    return values


def _reset(prefix: str) -> None:
    for key in list(st.session_state):
        if key.startswith(prefix + ":"):
            del st.session_state[key]


def _select_neighbor(key: str, available: list[str], step: int) -> None:
    """Button callbacks run before the selectbox is instantiated on the rerun."""
    current = st.session_state.get(key)
    if current not in available:
        return
    index = available.index(current) + step
    if 0 <= index < len(available):
        st.session_state[key] = available[index]


def _navigation(author: str, phase: str, records: list[dict]) -> str | None:
    counts = Counter(row["state"] for row in records)
    a, b, c, d = st.columns(4)
    a.metric("Concluídos", counts["complete"])
    b.metric("Rascunhos", counts["draft"])
    c.metric("Não iniciados", counts["not_started"])
    d.metric("Com correções", counts["needs_correction"])
    filter_key = f"{author}:{phase}:filter"
    selected_filter = _option("Mostrar", list(STATES), "all", filter_key, lambda x: STATES[x])
    available = [row["id"] for row in records
                 if selected_filter == "all" or row["state"] == selected_filter]
    if not available:
        st.info("Não há itens neste filtro.")
        return None
    key = f"{author}:{phase}:selected"
    if key in st.session_state and st.session_state[key] not in available:
        del st.session_state[key]
    selected = st.selectbox("Cenário" if phase == "scenario" else "Proposta",
                            available, key=key)
    index = available.index(selected)
    left, right = st.columns(2)
    left.button("← Anterior", disabled=index == 0, key=f"{author}:{phase}:prev",
                on_click=_select_neighbor, args=(key, available, -1))
    right.button("Seguinte →", disabled=index == len(available) - 1,
                 key=f"{author}:{phase}:next", on_click=_select_neighbor,
                 args=(key, available, 1))
    st.caption("Guarda o rascunho antes de mudar de item. Alterações não guardadas não são persistidas.")
    return selected


def _annotation_page(root: Path, author: str, phase: str) -> None:
    st.header("Fase A · Cenários" if phase == "scenario" else "Fase B · Propostas concretas")
    try:
        prepare(root, author, phase)
        records = items(root, author, phase)
    except (ValueError, OSError) as exc:
        if phase == "proposal":
            st.info("A fase B só fica disponível depois de ambos os autores concluírem e "
                    "adjudicarem o cenário das propostas importadas.")
        st.warning(str(exc))
        return
    if not records:
        st.info("Ainda não existem propostas B importadas para anotação.")
        return
    selected = _navigation(author, phase, records)
    if selected is None:
        return
    try:
        packet, form, digest = load_item(root, author, phase, selected)
    except (ValueError, OSError, KeyError) as exc:
        st.error(f"Este formulário necessita de correção: {exc}")
        return
    prefix = f"{author}:{phase}:{selected}"
    st.session_state.setdefault(prefix + ":revision", digest)
    st.divider()
    _scenario_view(packet) if phase == "scenario" else _proposal_view(packet)
    st.divider()
    st.subheader("A tua anotação")
    values = _scenario_fields(form, prefix) if phase == "scenario" else _proposal_fields(form, prefix)
    st.caption(f"Estado guardado: {form['status']}. Guardar rascunho permite campos incompletos; "
               "concluir aplica a validação do contrato Pydantic.")
    confirm_completed = st.checkbox("Confirmo a alteração de uma anotação já concluída",
                                    key=prefix + ":confirm") if form["status"] == "complete" else False
    left, right = st.columns(2)
    action = "draft" if left.button("Guardar rascunho", key=prefix + ":draft") else (
        "complete" if right.button("Validar e concluir", key=prefix + ":complete") else None)
    if action:
        data = {**form, **values, "status": action}
        try:
            save_form(root, author, phase, selected, data,
                      st.session_state[prefix + ":revision"],
                      confirm_completed=confirm_completed)
        except (ValueError, OSError) as exc:
            st.error(f"Não foi guardado: {exc}")
        else:
            _reset(prefix)
            st.success("Rascunho guardado." if action == "draft" else "Anotação concluída.")
            st.rerun()


def _comparison_page(root: Path) -> None:
    st.header("Comparação e adjudicação")
    st.warning("Área de consenso: abrir apenas depois de ambos os autores fecharem a anotação "
               "independente do item. A seleção do autor na barra lateral não é autenticação.")
    phase = st.radio("Fase", ["scenario", "proposal"], horizontal=True,
                     format_func=lambda x: "Cenários" if x == "scenario" else "Propostas")
    try:
        available = paired_ids(root, phase)
    except (ValueError, OSError) as exc:
        st.error(str(exc))
        return
    if not available:
        st.info("Ainda não há itens concluídos pelos dois autores nesta fase. "
                "As respostas individuais permanecem ocultas.")
        return
    report = comparison(root, phase)
    st.write(f"**Pares concluídos:** {report['complete_pairs']}")
    if phase == "proposal":
        st.write(f"**Concordância observada:** {report['observed_agreement']}")
        st.write(f"**Cohen's kappa:** {report['cohens_kappa'] if report['cohens_kappa'] is not None else 'indefinido'}")
        st.write("**Desacordos de decisão:**", report["decision_disagreements"])
        st.write("**Desacordos de aceitabilidade:**", report["scheduling_disagreements"])
    else:
        st.write("**Ambiguidade diferente:**", report["ambiguity_disagreements"])
        st.write("**Resultados a comparar em texto:**", report["outcome_text_review_required"])
        st.write("**Restrições a comparar em texto:**", report["hard_constraint_text_review_required"])
    selected = st.selectbox("Item para discussão", available, key=f"comparison:{phase}:selected")
    try:
        a, b = load_pair(root, phase, selected)
        form, digest = load_adjudication(root, phase, selected)
        packet, _, _ = load_item(root, AUTHORS[0], phase, selected)
    except (ValueError, OSError, KeyError) as exc:
        st.error(str(exc))
        return
    st.divider()
    _scenario_view(packet) if phase == "scenario" else _proposal_view(packet)
    left, right = st.columns(2)
    with left:
        st.subheader("Autor A")
        _individual_summary(a, phase)
    with right:
        st.subheader("Autor B")
        _individual_summary(b, phase)
    st.divider()
    st.subheader("Consenso a preencher pelos dois autores")
    prefix = f"adjudication:{phase}:{selected}"
    st.session_state.setdefault(prefix + ":revision", digest)
    values = _scenario_fields(form, prefix, adjudication=True) if phase == "scenario" else _proposal_fields(
        form, prefix, adjudication=True)
    both_agreed = st.checkbox("Ambos os autores discutiram e aprovaram este consenso",
                              key=prefix + ":both")
    confirm_completed = st.checkbox("Confirmo a alteração de um consenso já concluído",
                                    key=prefix + ":confirm") if form["status"] == "complete" else False
    x, y = st.columns(2)
    action = "draft" if x.button("Guardar rascunho do consenso", key=prefix + ":draft") else (
        "complete" if y.button("Validar e concluir consenso", key=prefix + ":complete") else None)
    if action:
        if action == "complete" and not both_agreed:
            st.error("É necessário confirmar que os dois autores aprovaram o consenso.")
            return
        data = {**form, **values, "status": action,
                "resolved_by": list(AUTHORS) if action == "complete" else form["resolved_by"]}
        try:
            save_adjudication(root, phase, selected, data,
                              st.session_state[prefix + ":revision"],
                              confirm_completed=confirm_completed)
        except (ValueError, OSError) as exc:
            st.error(f"Consenso não guardado: {exc}")
        else:
            _reset(prefix)
            st.rerun()
    status = adjudication_progress(root, phase)
    st.caption(f"Consensos concluídos: {len(status['complete'])}; pendentes: {len(status['pending'])}.")


def _individual_summary(form: dict, phase: str) -> None:
    if phase == "scenario":
        st.write("**Restrições:**", form["hard_constraints"])
        st.write("**Resultados aceitáveis:**", form["acceptable_outcomes"])
        st.write("**Impacto:**", form["impact_factors"])
        st.write("**Ambiguidade:**", form["ambiguity_present"], form["ambiguity_notes"])
    else:
        st.write("**Decisão:**", form["decision"].upper())
        st.write("**Justificação:**", form["decision_rationale"])
        st.write("**Scheduling aceitável:**", form["scheduling_acceptable"])
        st.write("**Impacto / risco:**", form["intervention_impact"], "/", form["intervention_risk"])
        st.write("**Fatores de risco:**", form["risk_factors"])
        if form["decision"] == "defer":
            st.write("**Motivos:**", [form["defer_reason_primary"], *form["defer_reason_additional"]])
            if form["clarification_question"]:
                st.write("**Pergunta:**", form["clarification_question"])


def _guide() -> None:
    st.header("Guia preliminar de autonomia")
    st.warning("Hipóteses para discussão entre os autores. Não são rótulos humanos nem regras automáticas.")
    st.markdown("""
**Primeiro, verifica a validade da proposta.** Campos em falta, alterações impossíveis ou
violações de restrições rígidas exigem correção/rejeição. Confirmação humana não torna
uma proposta inválida aplicável.

Para uma proposta válida, considera importância, impacto, ambiguidade, reversibilidade,
preferências explícitas, número/tipo de alterações e terceiros afetados.

- **ACT ilustrativo:** adicionar um bloco privado de estudo no horário livre pedido pelo utilizador.
- **DEFER ilustrativo:** mover uma reserva social que envolve outra pessoa, mesmo que o novo horário seja possível.
- **Inválida:** deslocar uma aula marcada como fixa ou adicionar um evento sem hora de início.

Quando a decisão for **DEFER**, escolhe um motivo principal e, se necessário, adicionais:
clarificação necessária, confirmação necessária, impacto elevado, impacto em terceiros
ou conflito de preferências. A pergunta de esclarecimento é opcional quando se escolhe
`clarification_required`. Estas razões são apenas metadados explicativos: o gate futuro
continua binário (`act/defer`) e não as recebe como features.
""")
    st.caption("Lê a política completa em docs/08_AUTONOMY_POLICY_DRAFT.md antes do piloto.")


def _v2_review_inputs(form: dict, prefix: str) -> dict:
    acceptable = st.selectbox("Solução de scheduling aceitável?", [None, "yes", "no"],
                              index=[None, "yes", "no"].index(form.get("scheduling_acceptable")),
                              format_func=lambda x: {None: "Por avaliar", "yes": "Sim", "no": "Não"}[x],
                              key=prefix + ":acceptable")
    decision = None
    if acceptable == "yes":
        decision = st.selectbox("Autonomia da proposta", [None, "act", "defer"],
                                index=[None, "act", "defer"].index(form.get("autonomy_decision")
                                                                     if form.get("autonomy_decision") in (None, "act", "defer") else None),
                                format_func=lambda x: "Por decidir" if x is None else x.upper(),
                                key=prefix + ":decision")
    if decision == "defer":
        primary = st.selectbox("Motivo principal", [""] + list(V2_DEFER_REASONS),
                               index=([""] + list(V2_DEFER_REASONS)).index(form.get("primary_reason")
                                                                              if form.get("primary_reason") in V2_DEFER_REASONS else ""),
                               key=prefix + ":reason")
        additional = st.multiselect("Outros motivos", [x for x in V2_DEFER_REASONS if x != primary],
                                    default=[x for x in form.get("additional_reasons", []) if x != primary],
                                    key=prefix + ":additional")
    else:
        primary = st.text_input("Motivo principal" + (" da rejeição" if acceptable == "no" else " para ACT"),
                                value=form.get("primary_reason", "") if form.get("autonomy_decision") != "defer" else "",
                                key=prefix + ":reason_text")
        additional = []
    justification = st.text_area("Justificação obrigatória para concluir", value=form.get("justification", ""),
                                 key=prefix + ":justification", height=140)
    return {"scheduling_acceptable": acceptable, "autonomy_decision": decision,
            "primary_reason": primary, "additional_reasons": additional,
            "justification": justification}


def _v2_scenario_and_proposal(source: dict) -> None:
    scenario = load_scenario_v2(ROOT / "data" / "scenarios_v2" / f"{source['scenario_id']}.json")
    st.subheader(f"Cenário {scenario.scenario_id}")
    st.info(scenario.user_request)
    profile = scenario.profile
    st.caption(f"Perfil: {profile.profile_id} · {profile.description} · fuso: {profile.timezone} · referência: {scenario.now.isoformat()}")
    packet, original, proposed, validation = preview_v2(ROOT, source)
    mode = st.radio("Calendário", ("Original", "Proposto"), horizontal=True,
                    key=f"v2:calendar:{source['proposal_id']}") if proposed is not None else "Original"
    if proposed is None:
        st.error("A simulação segura não conseguiu aplicar a proposta. O calendário original permanece intacto.")
    active_events = proposed if mode == "Proposto" and proposed is not None else original
    _weekly_calendar(packet, active_events,
                     mode="proposed" if mode == "Proposto" else "original")
    overlap_pairs = temporal_overlaps(active_events)
    if overlap_pairs:
        st.caption(f"Sobreposições temporais nesta vista ({len(overlap_pairs)} pares): "
                   + "; ".join(f"{a} / {b}" for a, b in overlap_pairs)
                   + ". Uma sobreposição não demonstra, por si só, violação de uma restrição.")
    st.caption("Calendário proposto: blocos com traço grosso = criados/movidos; blocos esbatidos = removidos/posição anterior. "
               "As categorias de eventos adicionados usam metadados neutros, porque o contrato Proposal não fornece categoria ou participantes.")
    with st.expander("Eventos originais em tabela"):
        st.dataframe(sorted(packet["calendar"], key=lambda e: e["start"]), hide_index=True)
    left, right = st.columns(2)
    with left:
        st.markdown("#### Restrições e preferências")
        for rule in profile.hard_constraints:
            st.write(f"• {rule.id} ({rule.rule_type}): {rule.description}")
        for pref in profile.soft_preferences:
            st.write(f"• {pref.id} ({pref.weight}/5): {pref.description}")
    with right:
        st.markdown("#### Prioridades e autonomia declarada")
        st.write(profile.priorities)
        st.write(profile.autonomy_preferences.model_dump())
    st.markdown("#### Proposta final")
    proposal = source["final_proposal"]
    for i, change in enumerate(proposal["changes"], 1):
        st.write(f"{i}. {change['type'].upper()} · {change.get('event_id') or change.get('title')} · "
                 f"{change.get('to_start') or ''} {change.get('to_end') or ''}")
    rationale = proposal["rationale"]
    st.write("**Justificação:**", rationale["summary"])
    st.write("**Restrições mencionadas:**", rationale["constraints"])
    st.write("**Prioridades mencionadas:**", rationale["priorities"])
    st.write("**Alternativas:**", rationale["alternatives_considered"])
    st.markdown("#### Avaliação técnica e Critic")
    st.write("**Validação técnica:**", validation)
    st.caption("Validação parcial: não prova satisfação do pedido nem validade das descrições em linguagem natural.")
    st.write(f"**Score final do Critic:** {source['critic_score']} · **Revisões:** {source['refinements']} · "
             f"**Estado B:** {source['source_status']}")
    with st.expander("Ver avaliações e iterações do Critic"):
        for step in source["iterations"]:
            st.write(f"**Iteração {step['index']}**")
            st.write("Proposta:", step.get("proposal"))
            st.write("Validação antes do Critic:", step.get("validation"))
            st.write("Avaliação do Critic:", step.get("critic_evaluation") or "sem avaliação")


def _v2_review_page(author: str) -> None:
    st.header("Avaliação direta das propostas · schema v2")
    st.caption("Cada autor vê apenas a sua avaliação. Guardar rascunho não exige campos completos.")
    try:
        all_records = records_v2(ROOT, author)
        sources = {row["proposal_id"]: row for row in catalog_v2(ROOT)}
    except (ValueError, OSError) as exc:
        st.error(str(exc))
        return
    if not all_records:
        st.info("Ainda não existem propostas v2 importadas. A geração B é uma ação CLI explícita.")
        return
    profiles = sorted({row["profile_id"] for row in all_records})
    families = sorted({row["family_id"] for row in all_records})
    scenarios = sorted({row["scenario_id"] for row in all_records})
    a, b, c, d = st.columns(4)
    profile_filter = a.selectbox("Perfil", ["Todos"] + profiles, key="v2:profile")
    family_filter = b.selectbox("Família", ["Todas"] + families, key="v2:family")
    scenario_filter = c.selectbox("Cenário", ["Todos"] + scenarios, key="v2:scenario")
    state_filter = d.selectbox("Estado", list(STATES), format_func=lambda x: STATES[x], key="v2:state")
    filtered = [row for row in all_records if (profile_filter == "Todos" or row["profile_id"] == profile_filter)
                and (family_filter == "Todas" or row["family_id"] == family_filter)
                and (scenario_filter == "Todos" or row["scenario_id"] == scenario_filter)
                and (state_filter == "all" or row["state"] == state_filter)]
    counts = Counter(row["state"] for row in all_records)
    st.caption(f"Progresso individual: {counts['complete']} concluídas, {counts['draft']} rascunhos, "
               f"{counts['not_started']} por iniciar, {counts['needs_correction']} com correções.")
    if not filtered:
        st.info("Nenhuma proposta neste filtro.")
        return
    available = [row["id"] for row in filtered]
    key = f"v2:{author}:selected"
    if st.session_state.get(key) not in available:
        st.session_state[key] = available[0]
    selected = st.selectbox("Proposta", available, key=key,
                            format_func=lambda pid: f"{sources[pid]['scenario_id']} · {pid}")
    idx = available.index(selected)
    prev, nxt = st.columns(2)
    prev.button("← Anterior", disabled=idx == 0, on_click=_select_neighbor,
                args=(key, available, -1), key=key + ":prev")
    nxt.button("Seguinte →", disabled=idx == len(available)-1, on_click=_select_neighbor,
               args=(key, available, 1), key=key + ":next")
    try:
        form, revision = load_review_v2(ROOT, author, selected)
        _v2_scenario_and_proposal(sources[selected])
    except (ValueError, OSError) as exc:
        st.error(f"O item precisa de correção: {exc}")
        return
    prefix = f"v2:{author}:{selected}"
    values = _v2_review_inputs(form.model_dump(), prefix)
    confirm = st.checkbox("Confirmo a substituição da minha avaliação concluída",
                          key=prefix + ":confirm") if form.status == "complete" else False
    x, y = st.columns(2)
    action = "draft" if x.button("Guardar rascunho", key=prefix + ":draft") else (
        "complete" if y.button("Concluir avaliação", key=prefix + ":complete") else None)
    if action:
        try:
            save_review_v2(ROOT, author, selected, {**form.model_dump(), **values, "status": action},
                           revision, confirm_completed=confirm)
        except (ValueError, OSError) as exc:
            st.error(f"Não foi guardado: {exc}")
        else:
            st.success("Avaliação guardada.")
            st.rerun()


def _v2_consensus_page() -> None:
    st.header("Comparação e adjudicação · propostas v2")
    report = compare_v2(ROOT)
    st.write(f"Pares concluídos: {len(report['complete_pairs'])}; concordância ACT/DEFER: "
             f"{report['observed_autonomy_agreement']}; Cohen's kappa: {report['cohens_kappa']}")
    st.write("Desacordos:", report["disagreements"])
    if not report["complete_pairs"]:
        st.info("A comparação só abre depois de ambos os autores concluírem a mesma proposta.")
        return
    pid = st.selectbox("Proposta para adjudicar", report["complete_pairs"], key="v2:consensus:selected")
    a, b, hashes = pair_v2(ROOT, pid)
    left, right = st.columns(2)
    left.write("**Autor A**")
    left.write(a.model_dump(exclude={"annotator_id", "proposal_id", "scenario_id"}))
    right.write("**Autor B**")
    right.write(b.model_dump(exclude={"annotator_id", "proposal_id", "scenario_id"}))
    consensus = load_consensus_v2(ROOT, pid)
    prefix = f"v2:consensus:{pid}"
    values = _v2_review_inputs(consensus.model_dump(), prefix)
    who = st.text_input("Quem efetuou a adjudicação?", value=consensus.adjudicated_by,
                        key=prefix + ":who")
    disagreements = st.multiselect("Campos em desacordo", ["scheduling_acceptable", "autonomy_decision", "primary_reason", "justification"],
                                   default=consensus.disagreements, key=prefix + ":disagreements")
    confirm = st.checkbox("Confirmo a alteração do consenso concluído", key=prefix + ":confirm") if consensus.status == "complete" else False
    action = "draft" if st.button("Guardar rascunho do consenso", key=prefix + ":draft") else (
        "complete" if st.button("Concluir consenso", key=prefix + ":complete") else None)
    if action:
        data = {**consensus.model_dump(), **values, "status": action,
                "adjudicated_by": who, "disagreements": disagreements,
                "original_review_sha256": hashes}
        try:
            save_consensus_v2(ROOT, pid, data, confirm_completed=confirm)
        except (ValueError, OSError) as exc:
            st.error(f"Consenso não guardado: {exc}")
        else:
            st.success("Consenso guardado.")
            st.rerun()


def main() -> None:
    st.title("HCAI · Anotação humana")
    st.caption("Interface local para os mesmos formulários JSON e validadores do projeto.")
    with st.sidebar:
        author = st.selectbox("Avaliador ativo", AUTHORS,
                              help="Separação operacional local; não é autenticação.")
        page = st.radio("Área", ["Propostas v2", "Consenso v2", "Arquivo: cenários antigos",
                                "Arquivo: propostas antigas", "Arquivo: comparação antiga", "Guia de autonomia"])
        st.caption("Cada autor trabalha apenas nos seus formulários. A comparação só abre itens concluídos pelos dois.")
    if page == "Propostas v2":
        _v2_review_page(author)
    elif page == "Consenso v2":
        _v2_consensus_page()
    elif page == "Arquivo: cenários antigos":
        _annotation_page(ROOT, author, "scenario")
    elif page == "Arquivo: propostas antigas":
        _annotation_page(ROOT, author, "proposal")
    elif page == "Arquivo: comparação antiga":
        _comparison_page(ROOT)
    else:
        _guide()


if __name__ == "__main__":
    main()
