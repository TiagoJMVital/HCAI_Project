import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from calendar_v2 import simulate  # noqa: E402
from final_dataset_v2 import final_manifest, scenario_path  # noqa: E402
from models import Proposal  # noqa: E402
from scenario_v2 import load_scenario  # noqa: E402


FIXTURE = ROOT / "eval" / "reference_proposals" / "deferred_invalid_repairs_v1.json"
ALLOWLIST = ROOT / "eval" / "pilot_scenario_allowlist.json"


def _fixtures() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["proposals"]


def test_repair_allowlist_matches_reference_fixture_and_final_train_split():
    expected = json.loads(ALLOWLIST.read_text(encoding="utf-8"))["scenario_ids"]
    fixture_ids = [item["scenario_id"] for item in _fixtures()]
    assert fixture_ids == expected

    rows = {row["scenario_id"]: row for row in final_manifest(ROOT, validate_scenarios=False)}
    assert all(rows[scenario_id]["split"] == "train" for scenario_id in expected)


def test_all_reference_proposals_pass_real_deterministic_validator():
    for item in _fixtures():
        scenario_id = item["scenario_id"]
        scenario = load_scenario(scenario_path(ROOT, scenario_id))
        proposal = Proposal.model_validate(item["proposal"])
        final_calendar, report = simulate(scenario, proposal)
        assert report["valid"], f"{scenario_id}: {report['violations']}"
        assert final_calendar is not None
        assert report["scope"] == "implemented_typed_checks_only"
