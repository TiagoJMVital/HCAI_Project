"""Deterministic configuration-C trainer for the exported Act/Defer dataset."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from benchmark_v2 import atomic_json

ROOT = Path(__file__).resolve().parent.parent
FEATURE_ORDER = (
    "intercept",
    "critic_score_div_5",
    "change_count_div_20",
    "max_touched_importance_div_5",
    "touches_fixed",
    "touches_third_party",
    "deletes_event",
    "moves_event",
    "adds_event",
    "change_type_add",
    "change_type_move",
    "change_type_delete",
    "change_type_mixed",
)


def vector(features: dict) -> list[float]:
    change_type = features["change_type"]
    if change_type not in {"add", "move", "delete", "mixed"}:
        raise ValueError(f"unknown change_type: {change_type}")
    return [
        1.0,
        float(features["critic_score"]) / 5.0,
        min(float(features["change_count"]), 20.0) / 20.0,
        float(features["max_touched_importance"]) / 5.0,
        float(bool(features["touches_fixed"])),
        float(bool(features["touches_third_party"])),
        float(bool(features["deletes_event"])),
        float(bool(features["moves_event"])),
        float(bool(features["adds_event"])),
        float(change_type == "add"),
        float(change_type == "move"),
        float(change_type == "delete"),
        float(change_type == "mixed"),
    ]


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-min(value, 40.0))
        return 1.0 / (1.0 + z)
    z = math.exp(max(value, -40.0))
    return z / (1.0 + z)


def _fit(rows: list[dict], *, epochs: int, learning_rate: float, l2: float) -> list[float]:
    if not rows:
        raise ValueError("cannot train gate without rows")
    labels = [int(row["label"] == "defer") for row in rows]
    counts = Counter(labels)
    class_weight = {label: len(labels) / (2 * count) for label, count in counts.items()}
    weights = [0.0] * len(FEATURE_ORDER)
    examples = [(vector(row["features"]), label) for row, label in zip(rows, labels)]
    for epoch in range(epochs):
        gradient = [0.0] * len(weights)
        for values, label in examples:
            probability = _sigmoid(sum(w * x for w, x in zip(weights, values)))
            error = class_weight[label] * (probability - label)
            for index, value in enumerate(values):
                gradient[index] += error * value
        rate = learning_rate / math.sqrt(1.0 + epoch / 500.0)
        for index in range(len(weights)):
            regularization = 0.0 if index == 0 else l2 * weights[index]
            weights[index] -= rate * (gradient[index] / len(examples) + regularization)
    return weights


def _probability(weights: list[float], row: dict) -> float:
    values = vector(row["features"])
    return _sigmoid(sum(weight * value for weight, value in zip(weights, values)))


def _metrics(scored: list[tuple[int, float]], threshold: float) -> dict:
    tp = tn = fp = fn = 0
    for label, probability in scored:
        predicted = int(probability >= threshold)
        tp += int(label == 1 and predicted == 1)
        tn += int(label == 0 and predicted == 0)
        fp += int(label == 0 and predicted == 1)
        fn += int(label == 1 and predicted == 0)
    total = len(scored)
    sensitivity = tp / (tp + fn) if tp + fn else None
    specificity = tn / (tn + fp) if tn + fp else None
    balanced = ((sensitivity + specificity) / 2
                if sensitivity is not None and specificity is not None else None)
    return {
        "n": total, "true_defer": tp + fn, "true_act": tn + fp,
        "true_positive_defer": tp, "true_negative_act": tn,
        "unsafe_act": fn, "unnecessary_defer": fp,
        "accuracy": (tp + tn) / total if total else None,
        "defer_recall": sensitivity, "act_recall": specificity,
        "balanced_accuracy": balanced,
    }


def _threshold(scored: list[tuple[int, float]], unsafe_act_cost: float) -> tuple[float, dict]:
    if not scored or len({label for label, _ in scored}) < 2:
        raise ValueError("threshold selection requires both act and defer labels")
    candidates = [index / 100 for index in range(5, 96)]
    ranked = []
    for threshold in candidates:
        metrics = _metrics(scored, threshold)
        cost = unsafe_act_cost * metrics["unsafe_act"] + metrics["unnecessary_defer"]
        ranked.append((cost, -(metrics["balanced_accuracy"] or 0.0), abs(threshold - 0.5),
                       threshold, metrics))
    _, _, _, selected, metrics = min(ranked)
    return selected, metrics | {"weighted_error_cost": ranked[candidates.index(selected)][0],
                                "unsafe_act_cost": unsafe_act_cost}


def _oof_scores(rows: list[dict], *, n_splits: int, epochs: int,
                learning_rate: float, l2: float) -> tuple[list[tuple[int, float]], list[dict]]:
    families = sorted({row["family_id"] for row in rows})
    if len(families) < 2:
        raise ValueError("grouped validation requires at least two families")
    n_splits = min(n_splits, len(families))
    if n_splits < 2:
        raise ValueError("grouped validation requires at least two folds")
    scored: list[tuple[int, float]] = []
    folds = []
    for index in range(n_splits):
        validation_families = families[index::n_splits]
        training = [row for row in rows if row["family_id"] not in validation_families]
        validation = [row for row in rows if row["family_id"] in validation_families]
        weights = _fit(training, epochs=epochs, learning_rate=learning_rate, l2=l2)
        fold_scores = [(int(row["label"] == "defer"), _probability(weights, row))
                       for row in validation]
        scored.extend(fold_scores)
        folds.append({"fold": index, "validation_families": validation_families,
                      "train_examples": len(training), "validation_examples": len(validation)})
    return scored, folds


def load_rows(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ValueError("gate dataset is empty")
    if any(row.get("split") != "train" for row in rows):
        raise ValueError("gate trainer accepts training rows only")
    if set(row.get("label") for row in rows) != {"act", "defer"}:
        raise ValueError("gate training requires both act and defer labels")
    return rows


def train(rows: list[dict], *, dataset_sha256: str, n_splits: int = 5,
          unsafe_act_cost: float = 5.0, epochs: int = 4000,
          learning_rate: float = 0.2, l2: float = 0.01) -> dict:
    scored, folds = _oof_scores(rows, n_splits=n_splits, epochs=epochs,
                                learning_rate=learning_rate, l2=l2)
    threshold, metrics = _threshold(scored, unsafe_act_cost)
    weights = _fit(rows, epochs=epochs, learning_rate=learning_rate, l2=l2)
    counts = Counter(row["label"] for row in rows)
    return {
        "schema_version": "1.0",
        "model_type": "deterministic_logistic_regression",
        "task": "learning_to_defer",
        "positive_label": "defer",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_sha256": dataset_sha256,
        "training_examples": len(rows),
        "label_counts": dict(sorted(counts.items())),
        "families": sorted({row["family_id"] for row in rows}),
        "review_protocols": sorted({row.get("review_protocol", "unknown") for row in rows}),
        "feature_order": list(FEATURE_ORDER),
        "coefficients": weights,
        "decision_threshold": threshold,
        "training_config": {"epochs": epochs, "learning_rate": learning_rate,
                            "l2": l2, "grouped_folds": min(n_splits, len(folds)),
                            "unsafe_act_cost": unsafe_act_cost},
        "grouped_oof": {"folds": folds, "metrics": metrics},
        "limitations": [
            "Training labels use the recorded review protocol and are not scheduling-quality labels.",
            "Grouped out-of-fold metrics on this small training set are model-selection diagnostics, not test results.",
            "The held-out test split remains locked and was not used by this trainer.",
        ],
    }


def predict(model: dict, features: dict) -> dict:
    if model.get("feature_order") != list(FEATURE_ORDER):
        raise ValueError("unsupported gate feature contract")
    probability = _probability(model["coefficients"], {"features": features})
    return {"decision": "defer" if probability >= model["decision_threshold"] else "act",
            "defer_probability": probability, "threshold": model["decision_threshold"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the deterministic v2 Learning-to-Defer gate")
    parser.add_argument("--dataset", type=Path,
                        default=ROOT / "data/gate_datasets/train.jsonl")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "data/gate_models/gate_v2.json")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--unsafe-act-cost", type=float, default=5.0)
    parser.add_argument("--epochs", type=int, default=4000)
    args = parser.parse_args()
    raw = args.dataset.read_bytes()
    model = train(load_rows(args.dataset), dataset_sha256=hashlib.sha256(raw).hexdigest(),
                  n_splits=args.folds, unsafe_act_cost=args.unsafe_act_cost,
                  epochs=args.epochs)
    atomic_json(args.output, model)
    metrics = model["grouped_oof"]["metrics"]
    print(f"trained {model['training_examples']} examples; threshold={model['decision_threshold']:.2f}; "
          f"OOF balanced_accuracy={metrics['balanced_accuracy']:.3f}; output={args.output}")


if __name__ == "__main__":
    main()
