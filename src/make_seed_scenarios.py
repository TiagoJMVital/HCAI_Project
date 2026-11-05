"""Gera 10 cenários iniciais (rascunho) em data/scenarios/.

Os cenários ficam com annotation_status='draft' e SEM anotações humanas:
os dois autores têm de anotar de forma independente (ver ANNOTATION.md).
Uso:  python src/make_seed_scenarios.py
"""
from __future__ import annotations

import json
from pathlib import Path

from models import CalendarEvent, Scenario

OUT = Path(__file__).resolve().parent.parent / "data" / "scenarios"

D = {"MON": "2026-11-09", "TUE": "2026-11-10", "WED": "2026-11-11", "THU": "2026-11-12", "FRI": "2026-11-13", "SAT": "2026-11-14"}


def ev(id, title, day, start, end, category="other", importance=3, fixed=False):
    return CalendarEvent(
        id=id, title=title, start=f"{D[day]}T{start}", end=f"{D[day]}T{end}",
        category=category, importance=importance, fixed=fixed,
    )


# eventos fixos da semana (iguais ao perfil)
def base_week():
    return [
        ev("cls_ml", "Machine Learning class", "TUE", "14:00", "16:00", "class", 5, True),
        ev("cls_hcai", "HCAI class", "WED", "10:00", "12:00", "class", 5, True),
        ev("cls_agents", "Agents lab", "THU", "09:00", "11:00", "class", 5, True),
        ev("gym_mon", "Gym", "MON", "18:00", "19:00", "gym", 2),
        ev("gym_wed", "Gym", "WED", "18:00", "19:00", "gym", 2),
        ev("gym_fri", "Gym", "FRI", "18:00", "19:00", "gym", 2),
    ]


NOW = "2026-11-08T20:00"
S = []


def add(**kw):
    S.append(Scenario(now=NOW, **kw))


# ---- família 1: hard_class (train) -------------------------------------
add(id="hard_class_01", family="hard_class", category="hard", difficulty="easy", split="train",
    user_request="Schedule a 1-hour call with my project partner on Wednesday morning.",
    calendar=base_week(), draft_label="act")
add(id="hard_class_02", family="hard_class", category="hard", difficulty="medium", split="train",
    user_request="Book a 90-minute group meeting on Tuesday afternoon, preferably after lunch.",
    calendar=base_week(), draft_label="act")

# ---- família 2: soft_gym_deadline (train) ------------------------------
dl = ev("dl_proj", "Project deadline", "WED", "23:59", "23:59", "academic_deadline", 5, True)
add(id="soft_gym_01", family="soft_gym_deadline", category="soft", difficulty="easy", split="train",
    user_request="I have the HCAI project due Wednesday at 23:59 and I'm behind. Free up time for it this week.",
    calendar=base_week() + [dl], draft_label="act")
add(id="soft_gym_02", family="soft_gym_deadline", category="soft", difficulty="medium", split="train",
    user_request="Project due Wednesday 23:59. I need at least 4 extra hours of focused work before then.",
    calendar=base_week() + [dl, ev("study_mon", "Study block", "MON", "20:00", "22:00", "study", 3)],
    draft_label="act")
add(id="soft_gym_03", family="soft_gym_deadline", category="soft", difficulty="hard", split="train",
    user_request="Project due Wednesday 23:59, but I also promised my brother I'd be at his birthday dinner Wednesday at 19:30.",
    calendar=base_week() + [dl, ev("bday", "Brother's birthday dinner", "WED", "19:30", "22:00", "social", 4)],
    draft_label="defer")

# ---- família 3: ambiguous_health (train) -------------------------------
add(id="amb_health_01", family="ambiguous_health", category="ambiguous", difficulty="medium", split="train",
    user_request="Something came up on Thursday morning, clear my calendar between 9 and 12.",
    calendar=base_week() + [ev("dentist", "Dentist appointment", "THU", "11:00", "12:00", "health", 4)],
    draft_label="defer")

# ---- família 4: soft_study_social (test) -------------------------------
add(id="soft_social_01", family="soft_study_social", category="soft", difficulty="easy", split="test",
    user_request="I need an extra study session before the ML quiz on Tuesday. Find me a slot on Monday.",
    calendar=base_week() + [ev("study_mon", "Study block", "MON", "20:00", "22:00", "study", 3),
                            ev("dinner_mon", "Dinner with friends", "MON", "19:30", "21:30", "social", 2)],
    draft_label="act")
add(id="soft_social_02", family="soft_study_social", category="soft", difficulty="medium", split="test",
    user_request="I want 3 hours of study for the ML quiz on Tuesday. Squeeze them in on Monday and Tuesday morning.",
    calendar=base_week() + [ev("study_mon", "Study block", "MON", "20:00", "22:00", "study", 3),
                            ev("coffee_tue", "Coffee with a classmate", "TUE", "10:00", "11:00", "social", 2)],
    draft_label="act")

# ---- família 5: ambiguous_supervisor (test) ----------------------------
add(id="amb_super_01", family="ambiguous_supervisor", category="ambiguous", difficulty="medium", split="test",
    user_request="Reschedule whatever is on Friday afternoon so I can work on the thesis.",
    calendar=base_week() + [ev("super_fri", "Meeting with supervisor", "FRI", "15:00", "16:00", "supervisor_meeting", 4)],
    draft_label="defer")
add(id="amb_super_02", family="ambiguous_supervisor", category="ambiguous", difficulty="hard", split="test",
    user_request="Cancel my Friday stuff, I'm too tired.",
    calendar=base_week() + [ev("super_fri", "Meeting with supervisor", "FRI", "15:00", "16:00", "supervisor_meeting", 4),
                            ev("lab_fri", "Lab demo", "FRI", "10:00", "11:30", "academic", 4)],
    draft_label="defer")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for s in S:
        (OUT / f"{s.id}.json").write_text(s.model_dump_json(indent=2), encoding="utf-8")
    print(f"{len(S)} cenários escritos em {OUT}")
