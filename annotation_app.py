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
from annotation_v2_ui import (FAMILY_DISPLAY_NAMES, active_proposed_events, local_packet,
                              preview as preview_v2, proposal_change_rows,
                              records as records_v2, reviewer_progress, temporal_overlaps)
from calendar_view import (
    identify_requested_interval, initial_week, overlap_summary,
    render_week_html, view_events, week_after,
)
from proposal_catalog_v2 import catalog as catalog_v2, training_catalog
from run_catalog_v2 import PILOT_SCENARIO_IDS, runs as runs_v2, status_matrix
from scenario_v2 import load_scenario as load_scenario_v2
from final_dataset_v2 import scenario_path as scenario_path_v2

st.set_page_config(page_title="HCAI · Human annotation", page_icon="📅", layout="wide")

STATES = {"all": "Todos", "not_started": "Não iniciados", "draft": "Rascunhos",
          "complete": "Concluídos", "needs_correction": "Precisam de correção"}


@st.cache_data(ttl=30, show_spinner=False)
def _training_sources_cached(root_label: str) -> list[dict]:
    """Avoid revalidating the full dataset/run catalogue on every widget rerun."""
    return training_catalog(Path(root_label))


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


def _side_by_side_calendars(packet: dict, original: list, proposed: list,
                            *, proposal_id: str) -> None:
    interval = identify_requested_interval(packet)
    base_week = initial_week(packet, interval)
    offset_key = f"v2:comparison-week:{proposal_id}"
    st.session_state.setdefault(offset_key, 0)
    nav_left, nav_middle, nav_right = st.columns([1, 2, 1])
    if nav_left.button("← Semana anterior", key=offset_key + ":previous"):
        st.session_state[offset_key] -= 1
    week = week_after(base_week, st.session_state[offset_key])
    if nav_middle.button(
            f"{week:%d/%m/%Y} – {(week + timedelta(days=6)):%d/%m/%Y} · semana inicial",
            key=offset_key + ":reset"):
        st.session_state[offset_key] = 0
        week = base_week
    if nav_right.button("Semana seguinte →", key=offset_key + ":next"):
        st.session_state[offset_key] += 1
        week = week_after(base_week, st.session_state[offset_key])
    left, right = st.columns(2)
    with left:
        st.markdown("#### Calendário original")
        st.html(render_week_html(original, week, interval, comparison_palette=True))
    with right:
        st.markdown("#### Calendário proposto")
        st.html(render_week_html(proposed, week, interval, comparison_palette=True))
    st.caption("Legenda: ⬜ cinzento — inalterado · 🟩 verde — adicionado · "
               "🟦 azul — movido/modificado · 🟥 vermelho — eliminado (apenas no resumo abaixo). "
               "Passe o cursor ou use Tab sobre um evento para ver título, horário e duração completos.")


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
    scenario = load_scenario_v2(scenario_path_v2(ROOT, run["scenario_id"]))
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
    scenario = load_scenario_v2(scenario_path_v2(ROOT, scenario_id))
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
        decision = st.selectbox(
                                "Can this concrete proposal be applied autonomously without prior human approval?",
                                [None, "act", "defer"],
                                index=[None, "act", "defer"].index(form.get("autonomy_decision")
                                                                     if form.get("autonomy_decision") in (None, "act", "defer") else None),
                                format_func=lambda x: ("Por decidir" if x is None else
                                    "ACT — pode ser aplicada autonomamente" if x == "act" else
                                    "DEFER — requer aprovação, clarificação ou intervenção humana"),
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
    scenario = load_scenario_v2(scenario_path_v2(ROOT, source["scenario_id"]))
    st.markdown("### Pedido original do utilizador")
    st.info(scenario.user_request)
    profile = scenario.profile
    packet, original, proposed, _validation = preview_v2(ROOT, source)
    if proposed is None:
        st.error("A proposta não produz um calendário aplicável segundo a validação determinística. "
                 "Avalie-a como solução de scheduling concreta; nenhuma alteração é mostrada como aplicada.")
        proposed_calendar = []
    else:
        proposed_calendar = active_proposed_events(proposed)
    _side_by_side_calendars(packet, original, proposed_calendar,
                            proposal_id=source["proposal_id"])
    overlap_pairs = temporal_overlaps(proposed_calendar)
    if overlap_pairs:
        st.caption(f"Sobreposições temporais no calendário proposto ({len(overlap_pairs)} pares): "
                   + "; ".join(f"{a} / {b}" for a, b in overlap_pairs)
                   + ". Uma sobreposição não demonstra, por si só, violação de uma restrição.")

    st.markdown("### Alterações propostas")
    proposal = source["final_proposal"]
    if not proposal["changes"]:
        st.info("0 alterações. Um calendário inalterado não prova, por si só, satisfação do pedido.")
    rows = proposal_change_rows(ROOT, source)
    counts = Counter(row["operation"] for row in rows)
    st.caption(f"{len(rows)} alterações — {counts['ADD']} adicionadas · "
               f"{counts['MOVE']} movidas/modificadas · {counts['DELETE']} eliminadas")
    if rows:
        display_rows = [{
            "Operação": ("🟢 ADD" if row["operation"] == "ADD" else
                         "🔵 MOVE" if row["operation"] == "MOVE" else "🔴 DELETE"),
            "Evento": row["event"],
            "Horário original": row["original_schedule"],
            "Horário proposto": row["proposed_schedule"],
            "Descrição": row["description"],
        } for row in rows]
        st.dataframe(display_rows, hide_index=True, width="stretch",
                     column_config={"Evento": st.column_config.TextColumn(width="large"),
                                    "Descrição": st.column_config.TextColumn(width="large")})
    rationale = proposal["rationale"]
    with st.expander("Justificação e alternativas apresentadas pelo Proposer"):
        st.write(rationale["summary"])
        st.write("**Restrições consideradas:**", rationale["constraints"])
        st.write("**Prioridades consideradas:**", rationale["priorities"])
        st.write("**Alternativas consideradas:**", rationale["alternatives_considered"])

    st.markdown("### Restrições e preferências completas")
    st.markdown("#### Restrições rígidas")
    for rule in profile.hard_constraints:
        st.write(f"**{rule.id}** · `{rule.rule_type}` — {rule.description}")
    if scenario.aggregate_requirements:
        st.markdown("#### Requisitos agregados tipados")
        for rule in scenario.aggregate_requirements:
            st.write(rule.model_dump(mode="json"))
    if scenario.confirmed_changes:
        st.markdown("#### Alterações externas confirmadas")
        for change in scenario.confirmed_changes:
            st.write(change.model_dump(mode="json"))
    st.markdown("#### Preferências suaves")
    for pref in profile.soft_preferences:
        st.write(f"**{pref.id}** · peso {pref.weight}/5 — {pref.description}")
    st.markdown("#### Preferências de autonomia declaradas")
    st.write(profile.autonomy_preferences.model_dump(mode="json"))
    st.markdown("#### Contexto do cenário")
    st.write(profile.description)
    st.write("**Prioridades declaradas:**", profile.priorities)
    st.caption(f"Fuso horário: {profile.timezone} · referência temporal: {scenario.now.isoformat()}")


def _v2_review_page(author: str) -> None:
    st.header("Anotação independente de propostas B de treino")
    st.caption("Cada avaliador vê apenas a sua própria anotação. IDs técnicos permanecem ocultos nesta área.")
    if st.button("Atualizar catálogo", key="v2:refresh-catalog",
                 help="Use após concluir ou importar novas runs B."):
        _training_sources_cached.clear()
        st.rerun()
    try:
        source_rows = _training_sources_cached(str(ROOT.resolve()))
        all_records = records_v2(ROOT, author, training_only=True, sources=source_rows)
        sources = {row["scenario_id"]: row for row in source_rows}
    except (ValueError, OSError) as exc:
        st.error(str(exc))
        return
    if not all_records:
        st.info("Ainda não existem propostas B de treino elegíveis e importadas.")
        return
    families = sorted({row["family_id"] for row in all_records})
    selector_left, selector_right = st.columns(2)
    family_key = f"v2:{author}:family"
    scenario_key = f"v2:{author}:scenario"
    family_id = selector_left.selectbox(
        "Profile family", families, key=family_key,
        format_func=lambda value: FAMILY_DISPLAY_NAMES.get(value, value))
    family_rows = sorted(
        (row for row in all_records if row["family_id"] == family_id),
        key=lambda row: row["scenario_id"])
    available = [row["scenario_id"] for row in family_rows]
    if st.session_state.get(scenario_key) not in available:
        st.session_state[scenario_key] = available[0]
    scenario_id = selector_right.selectbox(
        "Scenario", available, key=scenario_key, format_func=lambda value: value)
    selected = sources[scenario_id]["proposal_id"]

    progress = reviewer_progress(all_records, family_id)
    family_name = FAMILY_DISPLAY_NAMES.get(family_id, family_id)
    st.progress(progress["overall_complete"] / progress["overall_total"])
    st.caption(
        f"{family_name} — {progress['family_complete']}/{progress['family_total']} anotados · "
        f"{progress['family_remaining']} restantes. Progresso global: "
        f"{progress['overall_complete']}/{progress['overall_total']} anotados · "
        f"{progress['overall_remaining']} restantes.")
    next_unannotated = next((row["scenario_id"] for row in family_rows
                             if row["state"] != "complete" and row["scenario_id"] != scenario_id), None)
    if next_unannotated is not None:
        st.button("Ir para o próximo cenário não anotado", key=f"v2:{author}:next-unannotated",
                  on_click=lambda: st.session_state.update({scenario_key: next_unannotated}))

    try:
        form, revision = load_review_v2(ROOT, author, selected, source=sources[scenario_id])
        _v2_scenario_and_proposal(sources[scenario_id])
    except (ValueError, OSError) as exc:
        st.error(f"O item precisa de correção: {exc}")
        return

    st.markdown("### Anotação humana")
    st.info("Avalie a proposta concreta, não apenas se gosta do horário. Uma solução de scheduling "
            "de alta qualidade não é automaticamente elegível para execução autónoma. Considere "
            "incerteza, consequências, compromissos, permissões e preferências do utilizador. Uma "
            "proposta pode exigir aprovação humana mesmo quando satisfaz restrições; invalidade de "
            "scheduling ou consequências inaceitáveis também não devem ser ignoradas.")
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
                           revision, confirm_completed=confirm, source=sources[scenario_id])
        except (ValueError, OSError) as exc:
            st.error(f"Não foi guardado: {exc}")
        else:
            st.session_state[f"v2:{author}:saved"] = scenario_id
            st.rerun()
    if st.session_state.get(f"v2:{author}:saved") == scenario_id:
        st.success("Anotação guardada. Pode rever este cenário ou avançar para o próximo não anotado.")


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
