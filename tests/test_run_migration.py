import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))

from migrate_runs_scenario_first import apply_plan, build_plan  # noqa: E402
sys.path.insert(0, str(ROOT / "src"))
from run_paths_v2 import resolve_run_reference  # noqa: E402


def _artifact(root: Path, run_id: str, scenario_id: str, configuration: str = "A",
              *, content: bytes | None = None) -> Path:
    path = root / "eval/runs" / run_id / configuration / f"{scenario_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": "2.0", "run_id": run_id,
               "scenario_id": scenario_id, "configuration": configuration}
    path.write_bytes(content if content is not None else json.dumps(payload).encode())
    return path


def test_migration_preserves_hashes_auxiliary_files_and_is_idempotent(tmp_path):
    source = _artifact(tmp_path, "run1", "scenario_one")
    log = source.parent / "diagnostic.log"
    log.write_bytes(b"historical diagnostic\n")
    original = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (source, log)}

    plan = build_plan(tmp_path)
    assert plan["summary"]["artifacts_to_migrate"] == 2
    manifest = apply_plan(tmp_path, plan)
    result = tmp_path / "eval/runs/scenario_one/run1/A/scenario_one.json"
    migrated_log = tmp_path / "eval/runs/scenario_one/run1/A/diagnostic.log"
    assert hashlib.sha256(result.read_bytes()).hexdigest() == original[source.name]
    assert hashlib.sha256(migrated_log.read_bytes()).hexdigest() == original[log.name]
    assert manifest["summary"]["hashes_preserved"] is True
    assert resolve_run_reference(tmp_path, Path("eval/runs/run1/A/scenario_one.json")) == result
    assert build_plan(tmp_path)["moves"] == []


def test_migration_splits_multi_scenario_run_and_leaves_ambiguous_auxiliary(tmp_path):
    _artifact(tmp_path, "shared", "one", "A")
    _artifact(tmp_path, "shared", "two", "B")
    ambiguous = tmp_path / "eval/runs/shared/root.log"
    ambiguous.write_text("cannot safely assign")
    plan = build_plan(tmp_path)
    assert len(plan["moves"]) == 2
    assert any(item["path"].endswith("root.log") for item in plan["issues"])
    apply_plan(tmp_path, plan)
    assert ambiguous.exists()
    assert (tmp_path / "eval/runs/one/shared/A/one.json").exists()
    assert (tmp_path / "eval/runs/two/shared/B/two.json").exists()


def test_migration_detects_destination_conflict_before_moving(tmp_path):
    source = _artifact(tmp_path, "run1", "scenario_one")
    destination = tmp_path / "eval/runs/scenario_one/run1/A/scenario_one.json"
    destination.parent.mkdir(parents=True)
    destination.write_text(source.read_text())
    plan = build_plan(tmp_path)
    assert plan["collisions"]
    with pytest.raises(ValueError, match="collisions"):
        apply_plan(tmp_path, plan)
    assert source.exists()
