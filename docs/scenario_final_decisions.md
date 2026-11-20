# Remaining decisions after phase 6

The author-approved corrections from phase 6 have been applied. These **12** cases remain outside the pilot shortlist; they are distinct from legitimate uncertainty in a usable scenario. They are not ACT/DEFER labels. Exact status and source hashes are in [`scenario_final_status.csv`](scenario_final_status.csv).

| Scenario | Remaining blocker | Minimal next decision or evidence |
|---|---|---|
| `cleaning_lady_last_minute_construction_cleanup_001` | Client X's Tuesday block is already the requested reschedule; the former Thursday slot has no recoverable time. | Supply the original Thursday client slot or explicitly designate this a no-op case. |
| `content_creator_studio_maintenance_anniversary_001` | Technician and anniversary stream are already present; no remaining scheduling action is identifiable. | Supply the original conflicting block or designate an intentional no-op. |
| `high_school_student_catechesis_retreat_prep_004` | Friday packing is already fixed and the replaced Friday social event is absent. | Supply the original Friday social event or designate an intentional no-op. |
| `working_student_transit_strike_commute_delay_006` | Normal commute is restored and the premature home workout is removed, but the original gym trip and time are not recoverable. | Confirm the original gym event or accept a partial request that asks only to add home exercise. |
| `elite_athlete_student_international_competition_001` | The protected sleep ends at the exact 06:30 airport report time; departure travel and Sunday arrival are unknown. | Give confirmed travel/airport details or approve a narrowly defined sleep adjustment without inventing a return time. |
| `elite_athlete_student_injury_rehab_001` | Mandatory five-session physiotherapy frequency and clinic slot confirmations are not technically checked. | Confirm slots and decide whether human review alone is sufficient for a pilot; otherwise add a tested frequency rule. |
| `elite_athlete_student_sponsor_media_day_project_001` | Six task-specific project hours and completion by Friday are not proven by generic calendar time. | Provide a trustworthy task tag and decide the human quality check for completion. |
| `content_creator_medical_emergency_sponsor_001` | Sponsor completion by Friday is unverifiable; the category rule still freezes unrelated editing. | Confirm which editing block is obligatory and what evidence would establish completion. |
| `university_professor_grant_panel_resit_exam_005` | Two-exam completion is unverifiable; broad protection freezes flexible exam preparation. | Confirm which events are fixed and assess deadline satisfaction separately from calendar duration. |
| `university_professor_international_conference_exam_creation_002` | Final exam completion before travel is unverifiable; broad protection freezes flexible drafting. | Confirm which preparation events can move and assess task completion separately. |
| `nurse_shift_worker_masters_night_shift_cover_001` | The requested full post-shift sleep overlaps a fixed supervisor meeting. | Obtain a confirmed meeting change or explicitly accept that this scenario tests an unresolved external conflict. |
| `nurse_shift_worker_masters_night_shift_swap_001` | The requested full post-shift sleep overlaps a fixed supervisor meeting. | Obtain a confirmed meeting change or explicitly accept that this scenario tests an unresolved external conflict. |

The 86 ordinary pilot-ready cases and two intentional no-op cases remain available. “Ready with uncertainty” means a synthetic pilot may proceed while preserving explicit external or human-quality caveats; it never means an external condition has been verified.
