# Controlled Proposer–Critic pilot

The following ten **training-family** cases were selected from [`scenario_final_status.csv`](scenario_final_status.csv). They span the requested six themes. `ready_with_uncertainty` means the uncertainty must be inspected in the run; it is not a technical guarantee or an ACT/DEFER label. No test or development family is used.

| Theme | Scenario ID | Screening |
|---|---|---|
| Working student | `working_student_makeup_class_friday_family_dinner_008` | ready |
| Working student | `working_student_month_end_overtime_friday_005` | ready |
| Freelancer | `freelancer_flexible_medical_appointment_birthday_dinner_001` | ready; 32-hour sidecar |
| Freelancer | `freelancer_flexible_client_meeting_gaming_tournament_001` | ready with external uncertainty; 32-hour sidecar |
| Nurse | `nurse_shift_worker_masters_clinical_data_collection_001` | ready; daily thesis sidecar |
| Nurse | `nurse_shift_worker_masters_shift_changes_001` | ready with third-party uncertainty; exact confirmed shift exceptions |
| Athlete | `elite_athlete_student_exam_conflict_001` | ready with coach/transport uncertainty |
| Athlete | `elite_athlete_student_transport_strike_001` | ready |
| Content creator | `content_creator_agency_photoshoot_001` | ready |
| Parent | `parent_young_children_car_breakdown_solo_001` | ready with family context uncertainty |

Run from `HCAI_Project/` after authorizing the active import and IAedu calls. The first command imports **only these ten** into the active `train` split and preserves any already imported scenario. It does not run an LLM:

```bash
source .venv/bin/activate
PYTHONPATH=src python - <<'PY'
import csv
from pathlib import Path
from benchmark_v2 import import_scenario
root = Path.cwd()
ids = [
    'working_student_makeup_class_friday_family_dinner_008',
    'working_student_month_end_overtime_friday_005',
    'freelancer_flexible_medical_appointment_birthday_dinner_001',
    'freelancer_flexible_client_meeting_gaming_tournament_001',
    'nurse_shift_worker_masters_clinical_data_collection_001',
    'nurse_shift_worker_masters_shift_changes_001',
    'elite_athlete_student_exam_conflict_001',
    'elite_athlete_student_transport_strike_001',
    'content_creator_agency_photoshoot_001',
    'parent_young_children_car_breakdown_solo_001',
]
rows = {r['scenario_id']: r for r in csv.DictReader((root/'docs/scenario_final_status.csv').open())}
for sid in ids:
    row = rows[sid]
    assert row['split'] == 'train' and row['state'].startswith('ready_')
    target = root/'data/scenarios'/f'{sid}.json'
    if target.exists():
        print('already imported:', sid)
        continue
    print(import_scenario(root, root.parent/row['scenario_path'], 'train'))
PY
python src/benchmark_v2.py validate
```

For the **first controlled call**, use one scenario only. A and B call the LLM and write distinct new run directories; these commands are intentionally **not executed** in this preparation phase:

```bash
SCENARIO=working_student_makeup_class_friday_family_dinner_008
python eval/run_config_a_v2.py --only "$SCENARIO" --provider iaedu
python eval/run_config_b_v2.py --only "$SCENARIO" --provider iaedu --critic-provider iaedu
```

The runners print their exact result paths. Set `A_RESULT` and `B_RESULT` to those paths, then inspect the initial/final proposals, Critic iterations and technical validation without changing data:

```bash
A_RESULT='eval/runs/treino/trabalhadorEstudante/working_student_makeup_class_friday_family_dinner_008/<A_run_id>/A/working_student_makeup_class_friday_family_dinner_008.json'
B_RESULT='eval/runs/treino/trabalhadorEstudante/working_student_makeup_class_friday_family_dinner_008/<B_run_id>/B/working_student_makeup_class_friday_family_dinner_008.json'
python - "$A_RESULT" "$B_RESULT" <<'PY'
import json, sys
for path in sys.argv[1:]:
    run = json.load(open(path))
    print('\n', path, run['status'])
    for field in ('proposal', 'initial_proposal', 'iterations', 'final_proposal',
                  'technical_validation', 'final_result_calendar', 'decision', 'reasons'):
        if field in run:
            print(field, json.dumps(run[field], ensure_ascii=False, indent=2))
PY
```

Import a B result **only when suitable for human review** (the importer revalidates the run), then start the local annotation interface:

```bash
python src/proposal_catalog_v2.py "$B_RESULT"
streamlit run annotation_app.py --server.address 127.0.0.1
```

For the remaining nine, repeat the two runner commands with each exact ID above, inspecting one case before moving to the next. An A and B run started separately do not guarantee an identical initial LLM proposal; use B's stored `initial_proposal` for the within-run before/after comparison. Keep run IDs, prompt hashes and validation reports when comparing configurations. No test family or development family should be used to tune prompts after the test protocol is frozen.
