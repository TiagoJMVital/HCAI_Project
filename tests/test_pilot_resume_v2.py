import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
import run_pilot_v2 as pilot  # noqa: E402


def test_latest_terminal_skips_newer_failed_run(monkeypatch):
    rows = [
        {"status": "llm_error", "run_id": "failed"},
        {"status": "proposal_ready", "run_id": "successful"},
    ]
    monkeypatch.setattr(pilot, "runs", lambda *args, **kwargs: rows)
    assert pilot.latest_terminal("scenario", "A")["run_id"] == "successful"


def test_latest_terminal_returns_none_for_only_failed_runs(monkeypatch):
    monkeypatch.setattr(pilot, "runs", lambda *args, **kwargs: [
        {"status": "proposer_error", "run_id": "failed"},
    ])
    assert pilot.latest_terminal("scenario", "B") is None


def test_execute_passes_partial_b_to_documented_replay_option(monkeypatch, tmp_path):
    source = tmp_path / "partial.json"
    captured = {}
    monkeypatch.setattr(pilot.subprocess, "run",
                        lambda command, **kwargs: captured.update(command=command, kwargs=kwargs))
    monkeypatch.setattr(pilot, "runs", lambda *args, **kwargs: [{"_path": "result.json"}])
    path = pilot.execute("scenario", "B", initial_proposal_from=source)
    assert captured["command"][-2:] == ["--initial-proposal-from", str(source)]
    assert path == pilot.ROOT / "result.json"


def test_default_dry_run_lists_only_allowlisted_b_pairs(monkeypatch, capsys):
    monkeypatch.setattr(pilot, "latest_terminal", lambda *args, **kwargs: None)
    monkeypatch.setattr(sys, "argv", ["run_pilot_v2.py", "--dry-run"])
    assert pilot.main() == 0
    lines = capsys.readouterr().out.splitlines()
    run_lines = [line for line in lines if line.startswith("RUN ")]
    expected = pilot.load_allowlist(pilot.DEFAULT_ALLOWLIST)
    assert len(run_lines) == len(expected) == 10
    assert all(line.startswith("RUN B ") for line in run_lines)
    assert {line.split(maxsplit=2)[2] for line in run_lines} == set(expected)
