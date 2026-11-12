"""Expande as cinco bases originais para 20 bases e 41 variantes sintéticas.

Não cria anotações humanas nem altera os dez cenários originais.
"""
from __future__ import annotations

import json
from pathlib import Path

from make_seed_scenarios import NOW, S as SEEDS, base_week, ev
from models import Scenario

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "scenarios"
MANIFEST = ROOT / "data" / "benchmark_manifest.json"

LEGACY = {
    "hard_class_01": ("hard_class", {"duration_min": 60, "constraint": "HCAI class"}),
    "hard_class_02": ("hard_class", {"duration_min": 90, "constraint": "ML class"}),
    "soft_gym_01": ("soft_gym", {"extra_hours": "unspecified", "social_conflict": False}),
    "soft_gym_02": ("soft_gym", {"extra_hours": 4, "social_conflict": False}),
    "soft_gym_03": ("soft_gym", {"extra_hours": "unspecified", "social_conflict": True}),
    "amb_health_01": ("amb_health", {"request_specificity": "vague", "health_importance": 4}),
    "soft_social_01": ("soft_social", {"study_hours": "unspecified", "social_event": "dinner"}),
    "soft_social_02": ("soft_social", {"study_hours": 3, "social_event": "coffee"}),
    "amb_super_01": ("amb_super", {"request_action": "reschedule", "affected_events": 1}),
    "amb_super_02": ("amb_super", {"request_action": "cancel", "affected_events": 2}),
}

scenarios: list[Scenario] = list(SEEDS)
manifest: list[dict] = []
for scenario in SEEDS:
    base_id, factors = LEGACY[scenario.id]
    manifest.append({"scenario_id": scenario.id, "base_id": base_id,
                     "family": scenario.family, "split": scenario.split,
                     "category": scenario.category, "factors": factors,
                     "design_note": "variante original preservada"})


def add_variant(scenario_id: str, base_id: str, family: str, category: str,
                split: str, request: str, extras: list, difficulty: str,
                factors: dict, note: str) -> None:
    scenario = Scenario(id=scenario_id, family=family, category=category,
                        difficulty=difficulty, split=split, user_request=request,
                        now=NOW, calendar=base_week() + extras)
    scenarios.append(scenario)
    manifest.append({"scenario_id": scenario_id, "base_id": base_id,
                     "family": family, "split": split, "category": category,
                     "factors": factors, "design_note": note})


def pair(base_id: str, family: str, category: str, split: str, variants: list[tuple]) -> None:
    assert len(variants) == 2
    for n, (request, extras, difficulty, factors, note) in enumerate(variants, 1):
        add_variant(f"{base_id}_{n:02}", base_id, family, category, split,
                    request, extras, difficulty, factors, note)


# Segunda variante da base amb_health: muda especificidade e impacto, não a data.
add_variant("amb_health_02", "amb_health", "ambiguous_health", "ambiguous", "train",
            "Move only my flexible Thursday 11:00 appointment; keep the lab untouched.",
            [ev("checkup", "Routine checkup", "THU", "11:00", "12:00", "health", 2)],
            "medium", {"request_specificity": "explicit", "health_importance": 2},
            "pedido identifica o evento flexível e reduz o impacto")


# Família hard_class: mesma classe de restrição, pedidos e conflitos distintos.
pair("hard_exam", "hard_class", "hard", "train", [
    ("Add a 60-minute exam preparation meeting Wednesday 10:00-11:00.", [], "easy",
     {"slot_conflicts_fixed": True, "alternative_allowed": False},
     "pedido exige horário que colide com aula fixa"),
    ("Add a 60-minute exam preparation meeting Wednesday morning, any free slot.", [], "medium",
     {"slot_conflicts_fixed": True, "alternative_allowed": True},
     "janela flexível permite outra solução aceitável"),
])
pair("hard_lab", "hard_class", "hard", "train", [
    ("Book a one-hour project call Thursday at 09:30.", [], "easy",
     {"fixed_event": "agents_lab", "requested_time": "09:30"},
     "hora exata coincide com laboratório fixo"),
    ("Book a one-hour project call Thursday after 11:00.", [], "easy",
     {"fixed_event": "agents_lab", "requested_time": "after_11"},
     "mesma necessidade, janela fora do laboratório"),
])
pair("hard_travel", "hard_fixed_travel", "hard", "test", [
    ("Schedule a one-hour call on Friday afternoon without moving my fixed travel.",
     [ev("travel_fri", "Train journey", "FRI", "14:00", "17:00", "travel", 5, True)],
     "medium", {"fixed_travel": True, "free_afternoon_minutes": 60},
     "viagem fixa reduz opções de sexta-feira"),
    ("Schedule a one-hour call on Friday afternoon; the train booking is flexible.",
     [ev("travel_fri", "Train journey", "FRI", "14:00", "17:00", "travel", 3, False)],
     "hard", {"fixed_travel": False, "free_afternoon_minutes": 60},
     "flexibilidade da viagem altera o espaço de soluções"),
])


# Família soft_gym_deadline: urgência, impacto e flexibilidade do ginásio.
pair("gym_urgency", "soft_gym_deadline", "soft", "train", [
    ("The project is due Wednesday; reserve two hours to work before the deadline.",
     [ev("dl_proj", "Project deadline", "WED", "23:59", "23:59", "academic_deadline", 5, True)],
     "easy", {"deadline": "Wednesday", "required_work_hours": 2},
     "duas horas cabem em mais do que uma janela"),
    ("The project is due Wednesday; reserve five hours before the deadline without moving class.",
     [ev("dl_proj", "Project deadline", "WED", "23:59", "23:59", "academic_deadline", 5, True)],
     "hard", {"deadline": "Wednesday", "required_work_hours": 5},
     "maior duração exige trade-off mais forte"),
])
pair("gym_importance", "soft_gym_deadline", "soft", "train", [
    ("Free Wednesday evening for the project deadline; gym can move.",
     [ev("dl_proj", "Project deadline", "WED", "23:59", "23:59", "academic_deadline", 5, True)],
     "easy", {"gym_importance": 2, "gym_has_partner": False},
     "ginásio individual de baixo impacto"),
    ("Free Wednesday evening for the project deadline, but gym is a paid session with a partner.",
     [ev("dl_proj", "Project deadline", "WED", "23:59", "23:59", "academic_deadline", 5, True)],
     "hard", {"gym_importance": 4, "gym_has_partner": True},
     "compromisso com terceiro aumenta impacto de mover")
])
pair("gym_flexibility", "soft_gym_deadline", "soft", "train", [
    ("Create a project work block on Wednesday evening; move gym if necessary.",
     [ev("dl_proj", "Project deadline", "WED", "23:59", "23:59", "academic_deadline", 5, True)],
     "medium", {"gym_movable": True, "work_block_hours": 2},
     "ginásio flexível pode ser deslocado"),
    ("Create a project work block on Wednesday evening, but my Wednesday gym booking is fixed.",
     [ev("dl_proj", "Project deadline", "WED", "23:59", "23:59", "academic_deadline", 5, True)],
     "hard", {"gym_movable": False, "work_block_hours": 2},
     "reserva fixa impede solução de menor impacto")
])

# Mantém o mesmo evento de ginásio nas duas variantes; muda a sua importância
# ou flexibilidade, em vez de introduzir um segundo ginásio confundidor.
for scenario in scenarios:
    if scenario.id in {"gym_importance_02", "gym_flexibility_02"}:
        gym = next(e for e in scenario.calendar if e.id == "gym_wed")
        gym.importance = 4
        gym.title = "Paid training with partner" if scenario.id == "gym_importance_02" else "Non-refundable gym booking"
        gym.fixed = scenario.id == "gym_flexibility_02"


# Família ambiguous_health: ambiguidade, urgência e consequências de saúde.
pair("health_specificity", "ambiguous_health", "ambiguous", "train", [
    ("Clear Thursday afternoon; something medical came up.",
     [ev("physio", "Physiotherapy", "THU", "15:00", "16:00", "health", 4)],
     "medium", {"named_event": False, "health_importance": 4},
     "não identifica que compromisso médico mover"),
    ("Move my routine physiotherapy appointment Thursday 15:00 to Friday after 11:00.",
     [ev("physio", "Physiotherapy", "THU", "15:00", "16:00", "health", 2)],
     "medium", {"named_event": True, "health_importance": 2},
     "pedido explícito reduz incerteza")
])
pair("health_urgency", "ambiguous_health", "ambiguous", "train", [
    ("Find a free slot for a routine checkup this week.", [], "easy",
     {"urgency": "routine", "existing_health_event": False},
     "novo compromisso rotineiro com várias soluções"),
    ("I need urgent care on Monday; cancel whatever is in the way.",
     [ev("consult", "Specialist consultation", "MON", "16:00", "17:00", "health", 5)],
     "hard", {"urgency": "urgent", "existing_health_event": True},
     "pedido de cancelamento amplo e impacto elevado")
])
pair("health_tradeoff", "ambiguous_health", "ambiguous", "train", [
    ("Move Thursday's appointment to make room for study.",
     [ev("checkup", "Routine checkup", "THU", "15:00", "16:00", "health", 2)],
     "medium", {"appointment_importance": 2, "purpose": "study"},
     "compromisso de saúde rotineiro"),
    ("Move Thursday's specialist appointment to make room for study.",
     [ev("specialist", "Specialist appointment", "THU", "15:00", "16:00", "health", 5)],
     "hard", {"appointment_importance": 5, "purpose": "study"},
     "mesmo pedido afeta compromisso de saúde importante")
])


# Família soft_study_social: compromissos sociais e estudo em tensão.
pair("study_social_importance", "soft_study_social", "soft", "test", [
    ("Find two hours for quiz study Monday evening; coffee can move.",
     [ev("coffee_mon", "Coffee with friend", "MON", "19:00", "20:00", "social", 1)],
     "easy", {"social_importance": 1, "other_person_affected": False},
     "encontro social de baixo impacto"),
    ("Find two hours for quiz study Monday evening; my friend's farewell dinner is important.",
     [ev("farewell", "Friend's farewell dinner", "MON", "19:00", "21:00", "social", 5)],
     "hard", {"social_importance": 5, "other_person_affected": True},
     "compromisso social único e de maior impacto")
])
pair("study_social_flex", "soft_study_social", "soft", "test", [
    ("Add a study block before Tuesday's quiz; Monday dinner is flexible.",
     [ev("dinner_mon", "Casual dinner", "MON", "19:00", "20:00", "social", 2)],
     "medium", {"social_fixed": False, "study_min_hours": 1},
     "jantar pode ser movido se necessário"),
    ("Add a study block before Tuesday's quiz; Monday family dinner must stay.",
     [ev("dinner_mon", "Family dinner", "MON", "19:00", "20:00", "social", 4, True)],
     "hard", {"social_fixed": True, "study_min_hours": 1},
     "jantar fixo restringe a agenda")
])
pair("study_multi_solution", "soft_study_social", "soft", "test", [
    ("Find any two-hour study slot before Tuesday afternoon's quiz.", [], "easy",
     {"acceptable_windows": "many", "social_conflict": False},
     "várias janelas aceitáveis sem conflito social"),
    ("Find two hours of study before Tuesday afternoon's quiz while keeping Monday's farewell dinner.",
     [ev("farewell", "Farewell dinner", "MON", "19:00", "22:00", "social", 5, True)],
     "medium", {"acceptable_windows": "restricted", "social_conflict": True},
     "jantar fixo reduz janelas aceitáveis")
])


# Família ambiguous_supervisor: autonomia com impactos académicos e sociais.
pair("supervisor_importance", "ambiguous_supervisor", "ambiguous", "test", [
    ("Make room for thesis work Friday afternoon by moving the optional check-in.",
     [ev("super_fri", "Optional supervisor check-in", "FRI", "15:00", "16:00", "supervisor_meeting", 2)],
     "medium", {"meeting_importance": 2, "meeting_fixed": False},
     "reunião opcional de menor impacto"),
    ("Make room for thesis work Friday afternoon by moving the final thesis review.",
     [ev("super_fri", "Final thesis review", "FRI", "15:00", "16:00", "supervisor_meeting", 5, True)],
     "hard", {"meeting_importance": 5, "meeting_fixed": True},
     "revisão final fixa de impacto elevado")
])
pair("supervisor_clarity", "ambiguous_supervisor", "ambiguous", "test", [
    ("Move Friday's supervisor meeting to Monday at 15:00 and keep everything else.",
     [ev("super_fri", "Supervisor meeting", "FRI", "15:00", "16:00", "supervisor_meeting", 3)],
     "medium", {"target_slot_specified": True, "scope": "one_event"},
     "pedido específico para uma reunião"),
    ("Clear Friday afternoon for my thesis, whatever it takes.",
     [ev("super_fri", "Supervisor meeting", "FRI", "15:00", "16:00", "supervisor_meeting", 3)],
     "hard", {"target_slot_specified": False, "scope": "all_events"},
     "pedido vago pode afetar terceiros")
])
pair("supervisor_competing", "ambiguous_supervisor", "ambiguous", "test", [
    ("Reserve Friday afternoon for thesis work; move my personal reading block if needed.",
     [ev("reading_fri", "Reading block", "FRI", "15:00", "16:00", "study", 2)],
     "easy", {"affected_event": "personal", "impact": 2},
     "apenas compromisso pessoal flexível"),
    ("Reserve Friday afternoon for thesis work; there is also a supervisor meeting and group demo.",
     [ev("super_fri", "Supervisor meeting", "FRI", "15:00", "16:00", "supervisor_meeting", 4),
      ev("demo_fri", "Group demo", "FRI", "16:00", "17:00", "academic", 4)],
     "hard", {"affected_event": "third_parties", "impact": 5},
     "vários terceiros afetados e prioridade disputada")
])


def generate() -> tuple[int, int]:
    OUT.mkdir(parents=True, exist_ok=True)
    for scenario in scenarios:
        path = OUT / f"{scenario.id}.json"
        content = json.loads(scenario.model_dump_json())
        if path.exists():
            current = json.loads(path.read_text(encoding="utf-8"))
            if current != content:
                raise ValueError(f"cenário existente difere do gerador: {path.name}")
        else:
            path.write_text(scenario.model_dump_json(indent=2), encoding="utf-8")
    manifest_content = {"version": 1, "scenarios": manifest}
    MANIFEST.write_text(json.dumps(manifest_content, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    return len({row["base_id"] for row in manifest}), len(scenarios)


if __name__ == "__main__":
    bases, variants = generate()
    print(f"{bases} bases, {variants} variantes; manifesto em {MANIFEST}")
