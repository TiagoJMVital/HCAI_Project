import json
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

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


def test_discovers_new_and_legacy_runs_without_duplicate_entries(tmp_path):
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
        path = (tmp_path / "eval/runs" / "x" / record["run_id"] /
                record["configuration"] / "x.json")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(record))
    # An identical legacy artifact is tolerated during a staged migration and
    # must not create a duplicate catalogue entry.
    legacy = tmp_path / "eval/runs/a1/A/x.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps(failed))
    assert [item["run_id"] for item in runs(tmp_path, scenario_id="x")] == ["b1", "a1"]
    assert runs(tmp_path, scenario_id="x", configuration="A")[0]["_path"] == \
        "eval/runs/x/a1/A/x.json"
    _, events, validation = preview(tmp_path, success)
    assert events is not None and validation["valid"]
    assert len(status_matrix(tmp_path)) == 10


def test_legacy_layout_remains_readable(tmp_path):
    source = _scenario(tmp_path)
    record = {"schema_version": "2.0", "scenario_id": "x", "family": source["family_id"],
              "profile_id": source["profile"]["profile_id"], "split": "train",
              "configuration": "A", "run_id": "legacy", "status": "llm_error"}
    path = tmp_path / "eval/runs/legacy/A/x.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record))
    assert runs(tmp_path)[0]["run_id"] == "legacy"


@pytest.mark.parametrize(("function", "arguments", "heading"), [
    ("_a_results_page", "", "Resultados da configuração A"),
    ("_ab_comparison_page", "", "Comparação A/B · apenas leitura"),
])
def test_real_streamlit_result_pages_load_migrated_runs(tmp_path, function, arguments, heading):
    root = Path(__file__).resolve().parent.parent
    wrapper = tmp_path / f"{function}.py"
    wrapper.write_text(
        f"import sys\nsys.path.insert(0, {str(root)!r})\n"
        f"from pathlib import Path\nimport annotation_app\n"
        f"annotation_app.ROOT = Path({str(root)!r})\n"
        f"annotation_app.{function}({arguments})\n")
    app = AppTest.from_file(wrapper, default_timeout=15).run()
    assert not app.exception
    assert any(heading in item.value for item in app.header)
