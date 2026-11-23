import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from run_catalog_v2 import preview, runs, status_matrix  # noqa: E402


def _scenario(root: Path):
    source = Path(__file__).resolve().parent.parent / "data/scenarios/working_student_deadline_001.json"
    payload = json.loads(source.read_text())
    (root / "data/scenarios").mkdir(parents=True)
    (root / "data/scenarios/x.json").write_text(json.dumps(payload | {"scenario_id": "x"}))
    manifest = {"schema_version": "2.0", "scenarios": [{
        "scenario_id": "x", "family_id": payload["family_id"],
        "profile_id": payload["profile"]["profile_id"], "split": "train"}]}
    (root / "data/benchmark_manifest.json").write_text(json.dumps(manifest))
    return payload


def test_discovers_failures_and_previews_success_without_writes(tmp_path):
    source = _scenario(tmp_path)
    base = {"schema_version": "2.0", "scenario_id": "x", "family": source["family_id"],
            "profile_id": source["profile"]["profile_id"], "split": "train"}
    failed = base | {"configuration": "A", "run_id": "a1", "status": "llm_error"}
    success = base | {"configuration": "B", "run_id": "b1", "status": "proposal_ready",
                      "initial_proposal": {"changes": [], "rationale": {"constraints": [],
                          "priorities": [], "alternatives_considered": [], "summary": "initial"}},
                      "final_proposal": {"changes": [], "rationale": {"constraints": [],
                          "priorities": [], "alternatives_considered": [], "summary": "final"}}}
    for record in (failed, success):
        path = tmp_path / "eval/runs" / record["run_id"] / record["configuration"] / "x.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(record))
    assert [item["run_id"] for item in runs(tmp_path, scenario_id="x")] == ["b1", "a1"]
    _, events, validation = preview(tmp_path, success)
    assert events is not None and validation["valid"]
    assert len(status_matrix(tmp_path)) == 10
