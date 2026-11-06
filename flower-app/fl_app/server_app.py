"""Flower ServerApp: request one training round and aggregate client trees."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
from flwr.app import ConfigRecord, Context, Message, RecordDict
from flwr.serverapp import Grid, ServerApp
from sklearn.metrics import average_precision_score, f1_score, roc_auc_score, precision_recall_curve, precision_score, recall_score, confusion_matrix

from fl_app.tree_codec import decode_forests, schema_hash
from fl_app.protocol import read_checked
from fl_app.model_artifact import save_model


app = ServerApp()


@app.main()
def main(grid: Grid, context: Context) -> None:
    config = context.run_config
    mode = str(config.get("mode", "iid"))
    client_count = int(config.get("num-clients", 5))
    trees_per_client = int(config.get("trees-per-client", 20))
    seed = int(config.get("seed", 42))
    alpha = float(config.get("alpha", 0.5))
    data_root = Path(os.environ.get("PROJECT_DATA_ROOT", "data")).resolve()
    results_root = Path(os.environ.get("PROJECT_RESULTS_ROOT", "results")).resolve()
    split_dir = data_root / "experiments" / f"split_seed_{seed}"
    schema = json.loads((split_dir / "feature_schema.json").read_text(encoding="utf-8"))
    partition_dir = split_dir / ("iid" if mode == "iid" else f"non_iid/alpha_{alpha:g}") / f"clients_{client_count}"
    partition_summary = json.loads((partition_dir / "summary.json").read_text(encoding="utf-8"))
    if partition_summary["n_clients"] != client_count or partition_summary["mode"] != mode:
        raise ValueError("Partition summary does not match run configuration")
    expected_clients = {int(item["client_id"]): item for item in partition_summary["clients"]}
    if set(expected_clients) != set(range(1, client_count + 1)):
        raise ValueError("Partition summary is incomplete")
    features = schema["features"]
    target = schema["target"]

    deadline = time.monotonic() + 120
    nodes = sorted(grid.get_node_ids())
    while len(nodes) < client_count and time.monotonic() < deadline:
        time.sleep(2)
        nodes = sorted(grid.get_node_ids())
    if len(nodes) < client_count:
        raise RuntimeError(f"Expected {client_count} Flower nodes, found {len(nodes)}")

    messages = []
    for node_id in nodes[:client_count]:
        messages.append(Message(
            content=RecordDict({"config": ConfigRecord({
                "mode": mode,
                "trees_per_client": trees_per_client,
                "seed": seed,
                "alpha": alpha,
                "num_clients": client_count,
                "schema_hash": schema_hash(features),
            })}),
            message_type="train",
            dst_node_id=node_id,
        ))
    replies = list(grid.send_and_receive(messages, timeout=600))
    if len(replies) != client_count:
        raise RuntimeError(f"Expected {client_count} replies, got {len(replies)}")
    failures = [
        f"node {reply.metadata.src_node_id}: code={reply.error.code}, reason={reply.error.reason}"
        for reply in replies
        if reply.has_error()
    ]
    if failures:
        raise RuntimeError("Client replies failed:\n" + "\n".join(failures))

    payloads = []
    client_metrics = []
    seen = set()
    for reply in replies:
        meta = reply.content["meta"]
        client_id = int(meta["client_id"])
        if client_id in seen or client_id not in range(1, client_count + 1):
            raise ValueError("Duplicate or unexpected client ID")
        seen.add(client_id)
        if meta["schema_hash"] != schema_hash(features):
            raise ValueError("Client feature schema mismatch")
        expected = expected_clients[client_id]
        if meta["partition_sha256"] != expected["sha256"]:
            raise ValueError(f"Client {client_id} partition checksum mismatch")
        payloads.append({key: value.numpy() for key, value in reply.content["trees"].items()})
        metrics = reply.content["metrics"]
        if int(metrics["rows"]) != int(expected["rows"]):
            raise ValueError(f"Client {client_id} partition row count mismatch")
        client_metrics.append({"client_id": client_id, "rows": int(metrics["rows"]), "numeric_payload_bytes": int(metrics["numeric_payload_bytes"])})
    if seen != set(expected_clients):
        raise ValueError("Some client partitions were not represented")

    forest = decode_forests(payloads, features)
    if len(forest.trees) != client_count * trees_per_client:
        raise ValueError("Unexpected total tree count")
    validation = read_checked(split_dir / "validation.csv", schema)
    val_scores = forest.predict_proba(validation[features].to_numpy())[:, 1]
    p, r, candidate = precision_recall_curve(validation[target], val_scores)
    f1_candidates = 2 * p[:-1] * r[:-1] / np.maximum(p[:-1] + r[:-1], 1e-12)
    threshold = float(candidate[np.argmax(f1_candidates)])
    test = read_checked(split_dir / "test.csv", schema)
    score = forest.predict_proba(test[features].to_numpy())[:, 1]
    labels = test[target].to_numpy()
    prediction = (score >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(labels, prediction, labels=[0, 1]).ravel()
    result = {
        "mode": mode,
        "num_clients": client_count,
        "total_trees": len(forest.trees),
        "test_rows": len(test),
        "roc_auc": float(roc_auc_score(labels, score)),
        "average_precision": float(average_precision_score(labels, score)),
        "threshold_selected_on_validation": threshold,
        "f1": float(f1_score(labels, prediction, zero_division=0)),
        "precision": float(precision_score(labels, prediction, zero_division=0)),
        "recall": float(recall_score(labels, prediction, zero_division=0)),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "numeric_payload_bytes": sum(c["numeric_payload_bytes"] for c in client_metrics),
        "clients": sorted(client_metrics, key=lambda item: item["client_id"]),
    }
    results_root.mkdir(parents=True, exist_ok=True)
    model_dir = results_root / "models" / f"run_{context.run_id}"
    manifest_path = save_model(model_dir, forest, schema, threshold, context.run_id, mode)
    result["model_artifact"] = str(manifest_path)
    (results_root / f"flower_seed{seed}_{mode}_clients{client_count}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
