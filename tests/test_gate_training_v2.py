import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from train_gate_v2 import predict, train


def row(index: int, family: str, label: str) -> dict:
    defer = label == "defer"
    features = {
        "critic_score": 3.8 if defer else 4.5,
        "change_count": 5 if defer else 1,
        "change_type": "mixed" if defer else "add",
        "max_touched_importance": 5 if defer else 2,
        "touches_fixed": defer,
        "touches_third_party": defer,
        "deletes_event": defer,
        "moves_event": defer,
        "adds_event": True,
    }
    return {"proposal_id": f"p{index}", "family_id": family, "split": "train",
            "label": label, "review_protocol": "joint_consensus", "features": features}


def test_gate_training_is_deterministic_except_timestamp_and_predicts():
    rows = [row(i, f"family_{i % 3}", "defer" if i % 2 else "act") for i in range(18)]
    first = train(rows, dataset_sha256=hashlib.sha256(b"rows").hexdigest(),
                  n_splits=3, epochs=600)
    second = train(rows, dataset_sha256=hashlib.sha256(b"rows").hexdigest(),
                   n_splits=3, epochs=600)
    assert first["coefficients"] == second["coefficients"]
    assert first["decision_threshold"] == second["decision_threshold"]
    assert first["label_counts"] == {"act": 9, "defer": 9}
    assert first["grouped_oof"]["metrics"]["balanced_accuracy"] == 1.0
    assert predict(first, rows[0]["features"])["decision"] == rows[0]["label"]
    assert predict(first, rows[1]["features"])["decision"] == rows[1]["label"]
