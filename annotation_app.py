"""Local Streamlit client for independent direct reviews of final B proposals."""
from __future__ import annotations

import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from annotation_v2 import (
    AUTHORS, DEFER_REASONS as V2_DEFER_REASONS,
    compare as compare_v2, load_consensus as load_consensus_v2,
    load_review as load_review_v2, pair as pair_v2,
    save_consensus as save_consensus_v2, save_review as save_review_v2,
)
from annotation_v2_ui import (local_packet, preview as preview_v2, records as records_v2,
                              temporal_overlaps)
from calendar_view import (
    identify_requested_interval, initial_week, overlap_summary,
    render_week_html, view_events, week_after,
)
from proposal_catalog_v2 import catalog as catalog_v2
from run_catalog_v2 import PILOT_SCENARIO_IDS, runs as runs_v2, status_matrix
from scenario_v2 import load_scenario as load_scenario_v2

st.set_page_config(page_title="HCAI · Human annotation", page_icon="📅", layout="wide")

STATES = {"all": "Todos", "not_started": "Não iniciados", "draft": "Rascunhos",
          "complete": "Concluídos", "needs_correction": "Precisam de correção"}


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


def _select_neighbor(key: str, available: list[str], step: int) -> None:
    """Button callbacks run before the selectbox is instantiated on the rerun."""
    current = st.session_state.get(key)
    if current not in available:
        return
    index = available.index(current) + step
    if 0 <= index < len(available):
        st.session_state[key] = available[index]


def _run_label(run: dict) -> str:
    when = run.get("generated_at") or "sem data"
    return f"{when} · {run['status']} · {run['run_id']}"


def _proposal_details(title: str, raw: dict | None) -> None:
    st.markdown(f"#### {title}")
    if raw is None:
        st.info("Esta execução não produziu uma proposta estruturada.")
        return
    if not raw.get("changes"):
        st.info("Proposta sem alterações; isto não prova satisfação do pedido.")
    for index, change in enumerate(raw.get("changes", []), 1):
        st.write(f"{index}. {change['type'].upper()} · "
                 f"{change.get('event_id') or change.get('title')} · "
                 f"{change.get('to_start') or ''} {change.get('to_end') or ''}")
    rationale = raw.get("rationale") or {}
    st.write("**Justificação:**", rationale.get("summary"))
    st.write("**Restrições:**", rationale.get("constraints"))
    st.write("**Prioridades:**", rationale.get("priorities"))
    st.write("**Alternativas:**", rationale.get("alternatives_considered"))


def _run_metadata(run: dict) -> None:
    fields = ("run_id", "_path", "status", "generated_at", "seconds", "experiment_id",
              "repeat_index", "provider", "model", "proposer_provider", "proposer_model",
              "critic_provider", "critic_model", "prompt_versions", "generation_config",
              "proposer_generation_config", "critic_generation_config", "critic_settings",
              "scenario_sha256", "_active_scenario_sha256", "_scenario_hash_matches",
              "aggregate_requirements_sha256", "confirmed_changes_sha256")
    st.json({field: run.get(field) for field in fields if field in run}, expanded=False)


def _run_calendar(run: dict, *, initial: bool = False, key: str) -> None:
    raw = (run.get("initial_proposal") if initial else
           run.get("proposal") if run["configuration"] == "A" else run.get("final_proposal"))
    scenario = load_scenario_v2(ROOT / "data" / "scenarios" / f"{run['scenario_id']}.json")
    packet = local_packet(scenario)
    original = view_events(packet["calendar"])
    if raw is None:
        _weekly_calendar(packet, original, mode=f"original:{key}")
        return
    packet, _, proposed, recomputed = preview_v2(
        ROOT, {"scenario_id": run["scenario_id"], "final_proposal": raw})
    if proposed is None:
        st.error("A proposta não pode ser aplicada; o calendário original permanece intacto.")
        _weekly_calendar(packet, original, mode=f"original:{key}")
    else:
        _weekly_calendar(packet, proposed, mode=f"result:{key}")
    if run.get("technical_validation") is not None and not initial:
        st.write("**Validação gravada:**", run["technical_validation"])
    st.write("**Validação recalculada:**", recomputed)


def _scenario_header(scenario_id: str) -> None:
    scenario = load_scenario_v2(ROOT / "data" / "scenarios" / f"{scenario_id}.json")
    st.subheader(f"Cenário {scenario.scenario_id}")
    st.info(scenario.user_request)
    st.caption(f"Família: {scenario.family_id} · perfil: {scenario.profile.profile_id} · "
               f"{scenario.profile.description} · fuso: {scenario.profile.timezone}")
    with st.expander("Perfil, restrições e preferências"):
        st.json(scenario.profile.model_dump(mode="json"), expanded=False)


def _critic_history(run: dict) -> None:
    st.markdown("#### Histórico do Critic")
    if not run.get("iterations"):
        st.info("Sem iterações do Critic nesta execução.")
        return
    for step in run["iterations"]:
        with st.expander(f"Iteração {step.get('index')}"):
            st.write("Feedback para o Proposer:", step.get("proposer_feedback") or "não aplicável")
            st.write("Proposta:", step.get("proposal"))
            st.write("Validação:", step.get("validation"))
            st.write("Avaliação do Critic:", step.get("critic_evaluation") or "não realizada")
            st.write("Política de aceitação:", step.get("acceptance_policy") or "não disponível")
            st.write("Condições não verificadas:",
                     step.get("unresolved_assumptions", "não avaliadas"))
            if step.get("result_calendar"):
                st.write("Calendário resultante desta iteração:", step["result_calendar"])


def _a_results_page() -> None:
    st.header("Resultados da configuração A · apenas leitura")
    matrix = status_matrix(ROOT)
    st.dataframe([{"scenario_id": row["scenario_id"], "A runs": len(row["A"]),
                   "estado mais recente": row["A"][0]["status"] if row["A"] else "sem run"}
                  for row in matrix], hide_index=True)
    scenario_id = st.selectbox("Cenário piloto", PILOT_SCENARIO_IDS, key="a:scenario")
    available = runs_v2(ROOT, scenario_id=scenario_id, configuration="A")
    _scenario_header(scenario_id)
    if not available:
        st.warning("Ainda não existe uma execução A para este cenário.")
        return
    selected_id = st.selectbox("Execução A", [row["run_id"] for row in available],
                               format_func=lambda rid: _run_label(next(r for r in available if r["run_id"] == rid)),
                               key="a:run")
    run = next(row for row in available if row["run_id"] == selected_id)
    st.write(f"**Estado:** {run['status']} · **Decisão simulada:** "
             f"{run.get('decision') or 'indisponível'} · **Razões:** {run.get('reasons') or []}")
    if run.get("error"):
        st.error(run["error"])
    _proposal_details("Proposta final A", run.get("proposal"))
    scenario = load_scenario_v2(ROOT / "data/scenarios" / f"{scenario_id}.json")
    packet = local_packet(scenario)
    st.markdown("#### Calendário original")
    _weekly_calendar(packet, view_events(packet["calendar"]),
                     mode=f"original:A:{run['run_id']}")
    st.markdown("#### Calendário resultante A")
    _run_calendar(run, key=f"A:{run['run_id']}")
    with st.expander("Metadados da execução A"):
        _run_metadata(run)


def _ab_comparison_page() -> None:
    st.header("Comparação A/B · apenas leitura")
    st.caption("A e B fazem chamadas iniciais independentes. Diferenças entre A e B não são, por si só, efeito do Critic.")
    scenario_id = st.selectbox("Cenário piloto", PILOT_SCENARIO_IDS, key="ab:scenario")
    _scenario_header(scenario_id)
    a_runs = runs_v2(ROOT, scenario_id=scenario_id, configuration="A")
    b_runs = runs_v2(ROOT, scenario_id=scenario_id, configuration="B")
    selectors = st.columns(2)
    chosen = []
    for column, label, available in zip(selectors, ("A", "B"), (a_runs, b_runs)):
        with column:
            if available:
                rid = st.selectbox(f"Execução {label}", [r["run_id"] for r in available],
                                   format_func=lambda value, rows=available: _run_label(next(r for r in rows if r["run_id"] == value)),
                                   key=f"ab:{label}:run")
                chosen.append(next(r for r in available if r["run_id"] == rid))
            else:
                st.warning(f"Sem execução {label}.")
                chosen.append(None)
    scenario = load_scenario_v2(ROOT / "data/scenarios" / f"{scenario_id}.json")
    packet = local_packet(scenario)
    st.markdown("#### Calendário original")
    _weekly_calendar(packet, view_events(packet["calendar"]), mode=f"original:ab:{scenario_id}")
    panels = st.columns(2)
    for column, label, run in zip(panels, ("A", "B"), chosen):
        with column:
            st.subheader(f"Configuração {label}")
            if run is None:
                continue
            st.write(f"**Estado:** {run['status']} · **Decisão:** {run.get('decision') or 'indisponível'}")
            st.write("**Razões:**", run.get("reasons") or [])
            if run.get("error"):
                st.error(run["error"])
            if label == "B":
                _proposal_details("Proposta inicial B", run.get("initial_proposal"))
            _proposal_details(f"Proposta final {label}",
                              run.get("proposal") if label == "A" else run.get("final_proposal"))
            st.markdown(f"#### Calendário resultante {label}")
            _run_calendar(run, key=f"AB:{label}:{run['run_id']}")
            with st.expander(f"Metadados {label}"):
                _run_metadata(run)
    if chosen[1] is not None:
        _critic_history(chosen[1])
        st.write("**Incertezas finais B:**",
                 chosen[1].get("final_unresolved_assumptions", "não avaliadas"))


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
ou conflito de preferências. Estas razões são apenas metadados explicativos: o gate futuro
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
    scenario = load_scenario_v2(ROOT / "data" / "scenarios" / f"{source['scenario_id']}.json")
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
               "Eventos adicionados usam valores neutros para categoria, importância ou participantes quando esses metadados não forem fornecidos.")
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
    if not proposal["changes"]:
        st.info("Proposta sem alterações: a validação estrutural não demonstra que o pedido esteja satisfeito. Avalie a justificação e o calendário.")
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
    st.caption("proposal_ready indica aceitação da qualidade pelo Critic; não garante viabilidade externa "
               "nem constitui autorização para executar alterações.")
    st.caption(f"Política do Critic: {source.get('critic_policy_version') or 'histórica; revisão de plausibilidade não disponível'}")
    if "final_unresolved_assumptions" in source:
        pending = source["final_unresolved_assumptions"]
        if pending is None:
            st.caption("Condições externas finais: não avaliadas nesta proposta final.")
        elif pending:
            st.write("**Condições não verificadas na avaliação final:**")
            for entry in pending:
                st.write(f"{entry['subject']}: {entry['assumption']} · impacto potencial: "
                         f"{entry['potential_impact']} · fonte de verificação: {entry['verification_source']}")
                st.caption(f"Evidência em falta: {entry['evidence_gap']}")
        else:
            st.caption("O Critic não identificou condições externas por verificar na avaliação final; "
                       "isto não certifica viabilidade operacional.")
    else:
        st.caption("Condições externas estruturadas: não disponíveis nesta execução histórica.")
    with st.expander("Ver avaliações e iterações do Critic"):
        st.caption("As alternativas na justificação são opções ponderadas pelo Proposer; "
                   "apenas uma nova iteração após feedback do Critic conta como revisão. "
                   "Os problemas por iteração são observações do Critic, não provas de resolução automática.")
        for step in source["iterations"]:
            st.write(f"**Iteração {step['index']}**")
            if step.get("proposer_feedback"):
                st.write("Feedback recebido antes desta revisão:", step["proposer_feedback"])
                if step.get("operations_changed_from_previous") is not None:
                    st.write("Operações alteradas:", step["operations_changed_from_previous"],
                             "· Justificação alterada:", step["rationale_changed_from_previous"])
                if step.get("prior_critic_reviews"):
                    st.write("Dúvida anterior submetida de novo ao Critic:",
                             step["prior_critic_reviews"][-1]["plausibility_review"]["reason"])
            st.write("Proposta:", step.get("proposal"))
            st.write("Validação antes do Critic:", step.get("validation"))
            if step.get("result_calendar"):
                st.write("Calendário final simulado nesta iteração:",
                         step["result_calendar"]["events"])
            assessment = step.get("critic_evaluation")
            st.write("Avaliação do Critic:", assessment or "sem avaliação")
            if assessment:
                if "unresolved_assumptions" in assessment and assessment["unresolved_assumptions"] is not None:
                    st.write("Condições não verificadas nesta iteração:",
                             assessment["unresolved_assumptions"] or "nenhuma identificada")
                else:
                    st.caption("Condições estruturadas: não disponíveis nesta iteração histórica.")
                review = assessment.get("plausibility_review")
                policy = step.get("acceptance_policy")
                if review is None:
                    st.caption("Revisão estruturada de plausibilidade: não disponível nesta execução histórica.")
                else:
                    st.write("**Plausibilidade:** severidade", review["severity"],
                             "· revisão necessária:", review["revision_required"])
                    st.write("Fundamentação:", review["reason"] or "nenhuma observação relevante")
                    if step.get("prior_critic_reviews"):
                        st.caption("Reavaliação da dúvida anterior: "
                                   + ("continua a exigir revisão" if review["revision_required"]
                                      else "não exige nova revisão")
                                   + ". Consulte a fundamentação atual; isto não prova melhoria objetiva.")
                    if review["suggested_improvement"]:
                        st.write("Sugestão:", review["suggested_improvement"])
                    if policy:
                        st.write("Critérios numéricos cumpridos:", policy["numeric_criteria_passed"])
                        st.write("Política de aceitação aprovada:", policy["accepted"])
                        st.write("Motivos de revisão:", policy["revision_causes"] or "nenhum")
        history = source.get("uncertainty_history") or []
        if len(history) > 1 and any(item["unresolved_assumptions"] for item in history[:-1]):
            st.write("**Condições de iterações anteriores:**")
            final_list = source.get("final_unresolved_assumptions") or []
            for previous in history[:-1]:
                for entry in previous["unresolved_assumptions"]:
                    state = ("também indicada na avaliação final" if entry in final_list
                             else "resolução não confirmada")
                    st.write(f"Iteração {previous['iteration']} · {entry['subject']}: "
                             f"{entry['assumption']} · {state}")
            st.caption("O desaparecimento de uma condição da avaliação seguinte não prova que foi resolvida.")
        if source.get("unresolved_critic_weaknesses"):
            st.write("Problemas assinalados na última avaliação sem aceitação:",
                     source["unresolved_critic_weaknesses"])
        if source.get("unresolved_plausibility_review"):
            st.write("Revisão de plausibilidade ainda não resolvida:",
                     source["unresolved_plausibility_review"])


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
    st.title("HCAI · Piloto A/B e anotação humana")
    st.caption("Inspeção read-only de execuções e avaliação independente de propostas B.")
    with st.sidebar:
        author = st.selectbox("Avaliador ativo", AUTHORS,
                              help="Separação operacional local; não é autenticação.")
        page = st.radio("Área", ["Propostas", "Resultados A", "Comparação A/B",
                                 "Comparação e adjudicação", "Guia de autonomia"])
        st.caption("A comparação só abre depois de ambos os autores concluírem a proposta.")
    if page == "Propostas":
        _v2_review_page(author)
    elif page == "Resultados A":
        _a_results_page()
    elif page == "Comparação A/B":
        _ab_comparison_page()
    elif page == "Comparação e adjudicação":
        _v2_consensus_page()
    else:
        _guide()


if __name__ == "__main__":
    main()
