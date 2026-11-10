"""Create one protocol-checked central vs FL metrics CSV after both runs finish."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

METRICS = (
    "threshold", "roc_auc", "average_precision", "brier_score", "accuracy",
    "balanced_accuracy", "precision", "recall", "specificity", "f1",
    "false_positive_rate", "false_negative_rate", "positive_rate",
    "predicted_positive_rate", "test_rows", "tn", "fp", "fn", "tp",
)
POLICIES = ("default", "best_f1", "precision_at_recall")
CONFIG = {"max_depth": 10, "min_samples_leaf": 5, "max_features": "sqrt", "class_weight": None}


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def build(run_dir: Path, flower_path: Path | None, output: Path) -> None:
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if run["rf_config"] != CONFIG or run["central_trees"] != 100 or run["client_trees"] != 20:
        raise ValueError("Centralized RF configuration differs from the comparison protocol")
    local_rows = read_csv(run_dir / "test_metrics.csv")
    central = {row["policy"]: row for row in local_rows if row["model"] == "centralized"}
    if set(central) != set(POLICIES):
        raise ValueError("Rerun the updated notebook to export all centralized policies")
    if flower_path:
        fl = json.loads(flower_path.read_text(encoding="utf-8"))
        for key in ("source_sha256", "split_sha256", "feature_schema_sha256", "rf_config"):
            if fl.get(key) != run[key]:
                raise ValueError(f"Flower and centralized runs disagree on {key}; rerun or select matching results")
        if (fl.get("mode") != "iid" or fl.get("split_seed") != 42
                or fl.get("num_clients") != 5 or fl.get("trees_per_client") != 20
                or fl.get("total_trees") != run["central_trees"]):
            raise ValueError("Flower must be the matching 5-client, 100-tree IID run")
        federated = fl.get("test_metrics_by_policy", {})
        source = "azure_flower"
    else:
        federated = {row["policy"]: row for row in local_rows if row["model"] == "federated"}
        source = "local_simulation"
        fl = None
    if set(federated) != set(POLICIES):
        raise ValueError("Rerun updated Flower/notebook; full test_metrics_by_policy is missing")
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for policy in POLICIES:
        for model, values in (("centralized", central[policy]), ("federated", federated[policy])):
            missing = set(METRICS) - set(values)
            if missing:
                raise ValueError(f"{model} lacks metrics {sorted(missing)}; rerun updated code")
            row = {
                "model": model, "policy": policy,
                "execution": "centralized_local" if model == "centralized" else source,
                "protocol": run["protocol"], "seed": 42, "clients": 1 if model == "centralized" else 5,
                "trees": run["central_trees"], "source_sha256": run["source_sha256"],
                "test_sha256": run["split_sha256"]["test"],
                **{key: values[key] for key in METRICS},
                "train_seconds": run["central_train_seconds"] if model == "centralized" else "",
                "flower_round_seconds": fl["flower_round_seconds"] if model == "federated" and fl else "",
                "max_client_train_seconds": (fl["max_client_train_seconds"] if fl else max(c["train_seconds"] for c in run["client_log"])) if model == "federated" else "",
                "test_inference_seconds": (run["test_inference_seconds"]["centralized"] if model == "centralized" else fl["test_inference_seconds"] if fl else run["test_inference_seconds"]["federated"]),
                "numeric_payload_bytes": (fl["numeric_payload_bytes"] if fl else run["numeric_payload_bytes"]) if model == "federated" else 0,
                "max_client_blob_download_seconds": max(c["blob_download_seconds"] for c in fl["clients"]) if model == "federated" and fl and fl.get("data_backend") == "blob" else "",
                "total_client_blob_download_bytes": sum(c["data_bytes"] for c in fl["clients"]) if model == "federated" and fl and fl.get("data_backend") == "blob" else "",
                "server_eval_blob_download_seconds": sum(fl["evaluation_blob_download_seconds"].values()) if model == "federated" and fl and fl.get("data_backend") == "blob" else "",
                "source_file_bytes": run["source_file_bytes"],
            }
            rows.append(row)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} comparable policy rows to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=Path("results/protocol_v1/seed42_iid_clients5_trees20"))
    parser.add_argument("--flower", type=Path, help="New Azure Flower JSON; omit for local simulation")
    parser.add_argument("--output", type=Path, default=Path("results/comparison_metrics.csv"))
    args = parser.parse_args()
    build(args.run_dir, args.flower, args.output)
