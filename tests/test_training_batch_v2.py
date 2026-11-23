import argparse
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "eval")]

import run_training_b_v2 as batch  # noqa: E402
import migrate_runs_dataset_layout as layout_migration  # noqa: E402
from benchmark_v2 import import_scenario  # noqa: E402
from final_dataset_v2 import (BLOCKED_STATE, ELIGIBLE_STATES, FAMILY_FOLDERS,
                              final_manifest, run_prefix)  # noqa: E402
from llm import LLMError  # noqa: E402
from run_completion_v2 import (TechnicalRunError, historical_pilot_completed_b,
                               publish_completed_record)  # noqa: E402
from run_config_a_v2 import run_one as run_a  # noqa: E402
from run_config_b_v2 import run_one  # noqa: E402
from run_paths_v2 import resolve_run_reference  # noqa: E402
from scenario_v2 import load_scenario  # noqa: E402


class FakeProvider:
    name = "iaedu"
    model = "GPT-5.5"

    def generation_config(self):
        return {"max_retries": 2, "timeout_seconds": [10, 180]}


def test_final_manifest_distribution_and_paths():
    rows = final_manifest(ROOT, validate_scenarios=True)
    assert len(batch.select_rows(rows)) == 60
    assert len({row["scenario_id"] for row in rows}) == 100
    assert {run_prefix(row) for row in rows if row["split"] == "train"} == {
        ("treino", folder) for family, folder in FAMILY_FOLDERS.items()
        if any(item["family_id"] == family and item["split"] == "train" for item in rows)}
    assert {run_prefix(row) for row in rows if row["split"] == "dev"} == {
        ("avaliacao", "desenvolvimento", "secundario")}
    assert len({run_prefix(row) for row in rows if row["split"] == "test"}) == 3


def test_all_training_scenarios_are_eligible_and_unblocked():
    rows = [row for row in final_manifest(ROOT, validate_scenarios=True)
            if row["split"] == "train"]
    assert len(rows) == 60
    assert all(row["state"] in ELIGIBLE_STATES for row in rows)
    assert not any(row["state"] == BLOCKED_STATE for row in rows)


def test_phase7_surgical_scenario_corrections():
    rows = {row["scenario_id"]: row for row in final_manifest(ROOT, validate_scenarios=True)}

    medical = load_scenario(Path(rows[
        "content_creator_medical_emergency_sponsor_001"]["scenario_path"]))
    sponsor = next(rule for rule in medical.profile.hard_constraints
                   if rule.id == "sponsor_deadline")
    assert sponsor.rule_type == "protect_events_by_id"
    assert sponsor.event_ids == ["sponsor_edit_fri"]
    assert "Friday at 18:00" in medical.user_request

    studio = load_scenario(Path(rows[
        "content_creator_studio_maintenance_anniversary_001"]["scenario_path"]))
    events = {event.id: event for event in studio.calendar.events}
    assert events["gym_tue"].start.isoformat() == "2027-06-08T10:00:00+01:00"
    assert events["gym_tue"].fixed is True
    assert events["edit_tue"].start.isoformat() == "2027-06-08T12:30:00+01:00"
    assert events["stream_fri"].start.isoformat() == "2027-06-11T20:00:00+01:00"
    assert events["stream_fri"].fixed is False
    assert events["anniversary_stream_fri"].start.isoformat() == "2027-06-11T19:00:00+01:00"

    competition = load_scenario(Path(rows[
        "elite_athlete_student_international_competition_001"]["scenario_path"]))
    sleep = next(event for event in competition.calendar.events if event.id == "sleep_thu")
    assert sleep.start.isoformat() == "2027-03-03T22:00:00+00:00"
    assert sleep.end.isoformat() == "2027-03-04T05:30:00+00:00"
    assert "arrival time unknown" in competition.user_request

    strike = load_scenario(Path(rows[
        "working_student_transit_strike_commute_delay_006"]["scenario_path"]))
    assert "one-hour gap after work ends at 17:30" in strike.user_request
    assert "keep my 18:30 evening lecture intact" in strike.user_request
    assert "gym trip" not in strike.user_request

    uncertainty_only = {
        "nurse_shift_worker_masters_night_shift_cover_001",
        "nurse_shift_worker_masters_night_shift_swap_001",
        "elite_athlete_student_injury_rehab_001",
        "elite_athlete_student_sponsor_media_day_project_001",
    }
    assert {rows[scenario_id]["state"] for scenario_id in uncertainty_only} == {
        "ready_with_legitimate_uncertainty"}


def test_only_family_and_limit_selection_never_leak_evaluation():
    rows = final_manifest(ROOT)
    family = batch.select_rows(rows, family="criadorDeConteudo")
    assert len(family) == 10 and {row["split"] for row in family} == {"train"}
    one = batch.select_rows(rows, only=family[0]["scenario_id"])
    assert one == [family[0]]
    dev = next(row for row in rows if row["split"] == "dev")
    with pytest.raises(ValueError, match="development or test"):
        batch.select_rows(rows, only=dev["scenario_id"])


def test_dry_run_and_resume_do_not_execute(monkeypatch, tmp_path):
    rows = [
        {"scenario_id": "ready", "family_id": "content_creator_schedule_conflict",
         "profile_id": "p", "split": "train", "state": "ready_for_pilot",
         "state_reason": "ready", "scenario_path": str(tmp_path / "ready.json"),
         "scenario_sha256": "hash"},
        {"scenario_id": "done", "family_id": "content_creator_schedule_conflict",
         "profile_id": "p", "split": "train", "state": "ready_with_uncertainty",
         "state_reason": "ready", "scenario_path": str(tmp_path / "done.json"),
         "scenario_sha256": "hash"},
        {"scenario_id": "blocked", "family_id": "content_creator_schedule_conflict",
         "profile_id": "p", "split": "train", "state": "blocked_real_issue",
         "state_reason": "real issue", "scenario_path": str(tmp_path / "blocked.json"),
         "scenario_sha256": "hash"},
    ]
    monkeypatch.setattr(batch, "ROOT", tmp_path)
    monkeypatch.setattr(batch, "final_manifest", lambda *args, **kwargs: rows)
    monkeypatch.setattr(batch, "get_provider", lambda **kwargs: FakeProvider())
    monkeypatch.setattr(batch, "compatible_completed",
                        lambda root, row, proposer, critic: {"run_id": "old"}
                        if row["scenario_id"] == "done" else None)
    called = []
    args = argparse.Namespace(only=None, family=None, force=False, limit=1,
                              dry_run=True, delay=0, resume=True)
    code, summary = batch.execute_batch(args, execute=lambda *a, **k: called.append((a, k)))
    assert code == 0 and called == []
    assert summary["eligible"] == 2 and summary["blocked"] == 1
    assert summary["already_completed_total"] == 1
    assert summary["already_completed_compatible"] == 1 and summary["pending_selected"] == 1


def test_real_resume_recognizes_ten_manifest_authenticated_pilot_runs(monkeypatch, capsys):
    pilot = historical_pilot_completed_b(ROOT)
    assert len(pilot) == 10
    assert all(record["_completion_source"] == "historical_pilot_manifest"
               for record in pilot.values())

    monkeypatch.setattr(batch, "get_provider", lambda **kwargs: FakeProvider())
    monkeypatch.setattr(batch, "compatible_completed", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch, "atomic_json", lambda *args, **kwargs: None)
    args = argparse.Namespace(only=None, family=None, force=False, limit=None,
                              dry_run=True, delay=0, resume=True)
    code, summary = batch.execute_batch(args, execute=lambda *args, **kwargs: pytest.fail(
        "dry-run must not execute a scenario"))
    output = capsys.readouterr().out
    assert code == 0
    assert summary["already_completed_total"] == 10
    assert summary["already_completed_compatible"] == 0
    assert summary["already_completed_current"] == 0
    assert summary["already_completed_pilot"] == 10
    assert summary["pending_selected"] == 50
    assert output.count("ALREADY_COMPLETED_PILOT —") == 10
    assert output.count("WOULD RUN —") == 50


def test_pilot_manifest_identity_takes_precedence_over_newer_compatible_run(
        monkeypatch, tmp_path):
    row = {"scenario_id": "pilot", "family_id": "content_creator_schedule_conflict",
           "profile_id": "p", "split": "train", "state": "ready_for_pilot",
           "state_reason": "ready", "scenario_path": str(tmp_path / "pilot.json"),
           "scenario_sha256": "hash"}
    monkeypatch.setattr(batch, "ROOT", tmp_path)
    monkeypatch.setattr(batch, "final_manifest", lambda *args, **kwargs: [row])
    monkeypatch.setattr(batch, "get_provider", lambda **kwargs: FakeProvider())
    monkeypatch.setattr(batch, "historical_pilot_completed_b",
                        lambda root: {"pilot": {
                            "run_id": "historical", "family": row["family_id"],
                            "profile_id": row["profile_id"], "split": row["split"]}})
    monkeypatch.setattr(batch, "compatible_completed", lambda *args, **kwargs: pytest.fail(
        "pilot scenarios must be resolved from the authenticated migration manifest first"))
    args = argparse.Namespace(only=None, family=None, force=False, limit=None,
                              dry_run=True, delay=0, resume=True)
    code, summary = batch.execute_batch(args)
    assert code == 0
    assert summary["already_completed_pilot"] == 1
    assert summary["already_completed_current"] == 0
    assert summary["pending_selected"] == 0


def test_historical_pilot_resume_rejects_hash_mismatch(tmp_path):
    record = {
        "schema_version": "2.0", "scenario_id": "scenario", "run_id": "run",
        "configuration": "B", "status": "proposal_ready", "family": "family",
        "profile_id": "profile", "split": "train", "generated_at": "2026-01-01T00:00:00Z",
        "prompt_versions": {}, "iterations": [{}], "initial_proposal": {},
        "final_proposal": {}, "critic_settings": {},
    }
    relative = Path("eval/runs/treino/family/scenario/run/B/scenario.json")
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(record))
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "1.0",
        "moves": [{"destination": str(relative), "sha256": digest,
                   **{key: record[key] for key in
                      ("scenario_id", "run_id", "configuration", "status")}}],
    }
    manifest_path = tmp_path / "eval/dataset_layout_migration_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest))
    assert set(historical_pilot_completed_b(tmp_path)) == {"scenario"}
    target.write_text(json.dumps(record | {"status": "critic_error"}))
    with pytest.raises(ValueError, match="hash mismatch"):
        historical_pilot_completed_b(tmp_path)


class FailingProvider(FakeProvider):
    def generate_structured(self, *args, **kwargs):
        raise LLMError("invalid JSON", diagnostics={"classification": "structured_output_exhausted"})


def test_technical_runner_error_publishes_no_run(tmp_path):
    import_scenario(tmp_path, ROOT / "data/scenarios/working_student_deadline_001.json", "train")
    with pytest.raises(TechnicalRunError):
        run_one(tmp_path, "working_student_deadline_001", FailingProvider(), FakeProvider())
    assert list((tmp_path / "eval/runs").rglob("*.json")) == []


def test_a_error_and_interruption_publish_no_run(tmp_path):
    import_scenario(tmp_path, ROOT / "data/scenarios/working_student_deadline_001.json", "train")
    with pytest.raises(TechnicalRunError):
        run_a(tmp_path, "working_student_deadline_001", FailingProvider())
    class InterruptedProvider(FakeProvider):
        def generate_structured(self, *args, **kwargs):
            raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        run_one(tmp_path, "working_student_deadline_001", InterruptedProvider(), FakeProvider())
    assert list((tmp_path / "eval/runs").rglob("*.json")) == []


def test_atomic_publish_never_overwrites_and_cleans_failed_destination(monkeypatch, tmp_path):
    runs_root = tmp_path / "eval/runs"
    existing = runs_root / "treino/family/scenario/run/B/scenario.json"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"historical")
    with pytest.raises(FileExistsError):
        publish_completed_record(existing, {"new": True}, runs_root=runs_root)
    assert existing.read_bytes() == b"historical"

    target = runs_root / "treino/family/scenario/new/B/scenario.json"
    def broken(path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        raise OSError("disk failure")
    monkeypatch.setattr("benchmark_v2.atomic_json", broken)
    with pytest.raises(OSError, match="disk failure"):
        publish_completed_record(target, {}, runs_root=runs_root)
    assert not target.exists() and not target.parent.exists()


def test_dataset_layout_migration_preserves_terminal_and_removes_unreferenced_error(
        monkeypatch, tmp_path):
    row = {"scenario_id": "scenario", "family_id": "content_creator_schedule_conflict",
           "profile_id": "p", "split": "train"}
    monkeypatch.setattr(layout_migration, "final_manifest", lambda root: [row])
    terminal = {"schema_version": "2.0", "scenario_id": "scenario",
                "family": row["family_id"], "profile_id": "p", "split": "train",
                "run_id": "good", "configuration": "B", "status": "proposal_ready"}
    failed = terminal | {"run_id": "bad", "status": "critic_error",
                         "error_stage": "critic", "error": "invalid JSON"}
    for record in (terminal, failed):
        path = tmp_path / "eval/runs" / record["scenario_id"] / record["run_id"] / "B/scenario.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record))
    plan = layout_migration.build_plan(tmp_path)
    assert plan["summary"] == {"publishable_to_move": 1, "technical_errors_to_remove": 1,
                               "issues": 0, "collisions": 0}
    digest = plan["moves"][0]["sha256"]
    layout_migration.apply_plan(tmp_path, plan)
    target = tmp_path / "eval/runs/treino/criadorDeConteudo/scenario/good/B/scenario.json"
    assert target.exists() and layout_migration.sha256(target) == digest
    assert not any(path.name == "scenario.json" and "bad" in path.parts
                   for path in (tmp_path / "eval/runs").rglob("*.json"))


def test_legacy_replay_reference_resolves_archived_dependency(tmp_path):
    archive = tmp_path / "eval/historical_run_sources/scenario/run/B/scenario.json"
    archive.parent.mkdir(parents=True)
    archive.write_text(json.dumps({"run_id": "run", "scenario_id": "scenario"}))
    old = Path("eval/runs/run/B/scenario.json")
    assert resolve_run_reference(tmp_path, old) == archive
