"""Flower ServerApp: request one training round and aggregate client trees."""

from __future__ import annotations

import json
import hashlib
import os
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
from flwr.app import ConfigRecord, Context, Message, RecordDict
from flwr.serverapp import Grid, ServerApp
from fl_app.tree_codec import decode_forests, schema_hash
from fl_app.protocol import read_checked, sha256, validate_checked
from fl_app.model_artifact import save_model
from fl_app.evaluation import choose_thresholds, evaluate
from fl_app.blob_io import download_blob
from fl_app.cloud_artifacts import publish_run


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
    split_metadata_path = split_dir / "split_metadata.json"
    split_metadata = json.loads(split_metadata_path.read_text(encoding="utf-8"))
    if split_metadata["feature_schema_sha256"] != sha256(split_dir / "feature_schema.json"):
        raise ValueError("Feature schema checksum differs from split metadata")
    backend = os.environ.get("DATA_BACKEND", "vm")
    if backend not in {"vm", "blob"}:
        raise ValueError("DATA_BACKEND must be 'vm' or 'blob'")
    artifact_url = os.environ.get("ARTIFACT_BLOB_BASE_URL")
    if backend == "blob" and not artifact_url:
        raise RuntimeError("Set ARTIFACT_BLOB_BASE_URL before a Blob-backed Flower run")
    evaluation_frames = {}
    evaluation_download_seconds = {}
    evaluation_blob_bytes = {}
    for name in ("validation", "test"):
        if backend == "blob":
            base_url = os.environ.get("EVAL_BLOB_BASE_URL", "").rstrip("/")
            if not base_url:
                raise RuntimeError("Set EVAL_BLOB_BASE_URL when DATA_BACKEND=blob")
            source_bytes, seconds = download_blob(f"{base_url}/{name}.csv")
            digest = hashlib.sha256(source_bytes).hexdigest()
            evaluation_frames[name] = validate_checked(
                pd.read_csv(BytesIO(source_bytes)), schema, f"{name} Azure blob"
            )
            evaluation_download_seconds[name] = seconds
            evaluation_blob_bytes[name] = len(source_bytes)
        else:
            digest = sha256(split_dir / f"{name}.csv")
            evaluation_frames[name] = read_checked(split_dir / f"{name}.csv", schema)
        if split_metadata["split_sha256"][name] != digest:
            raise ValueError(f"{name} checksum differs from split metadata")
    partition_dir = split_dir / ("iid" if mode == "iid" else f"non_iid/alpha_{alpha:g}") / f"clients_{client_count}"
    partition_summary = json.loads((partition_dir / "summary.json").read_text(encoding="utf-8"))
    if partition_summary["split_sha256"] != sha256(split_metadata_path):
        raise ValueError("Partition summary belongs to another split")
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
    round_started_utc = datetime.now(timezone.utc).isoformat()
    round_started = time.perf_counter()
    replies = list(grid.send_and_receive(messages, timeout=600))
    round_seconds = time.perf_counter() - round_started
    round_finished_utc = datetime.now(timezone.utc).isoformat()
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
        client_metrics.append({
            "client_id": client_id, "rows": int(metrics["rows"]),
            "train_seconds": float(metrics["train_seconds"]),
            "data_read_seconds": float(metrics["data_read_seconds"]),
            "blob_download_seconds": float(metrics["blob_download_seconds"]),
            "data_bytes": int(metrics["data_bytes"]),
            "numeric_payload_bytes": int(metrics["numeric_payload_bytes"]),
        })
    if seen != set(expected_clients):
        raise ValueError("Some client partitions were not represented")

    forest = decode_forests(payloads, features)
    if len(forest.trees) != client_count * trees_per_client:
        raise ValueError("Unexpected total tree count")
    validation = evaluation_frames["validation"]
    val_scores = forest.predict_proba(validation[features].to_numpy())[:, 1]
    thresholds = choose_thresholds(validation[target], val_scores)
    threshold = thresholds["best_f1"]
    test = evaluation_frames["test"]
    inference_started = time.perf_counter()
    score = forest.predict_proba(test[features].to_numpy())[:, 1]
    inference_seconds = time.perf_counter() - inference_started
    labels = test[target].to_numpy()
    test_metrics = {policy: evaluate(labels, score, value) for policy, value in thresholds.items()}
    best = test_metrics["best_f1"]
    result = {
        "run_id": int(context.run_id),
        "protocol": "v1.0",
        "split_seed": seed,
        "source_sha256": split_metadata["source_sha256"],
        "split_sha256": split_metadata["split_sha256"],
        "feature_schema_sha256": split_metadata["feature_schema_sha256"],
        "rf_config": {"max_depth": 10, "min_samples_leaf": 5, "max_features": "sqrt", "class_weight": None},
        "mode": mode,
        "data_backend": backend,
        "num_clients": client_count,
        "trees_per_client": trees_per_client,
        "total_trees": len(forest.trees),
        "test_rows": len(test),
        "roc_auc": best["roc_auc"],
        "average_precision": best["average_precision"],
        "threshold_selected_on_validation": threshold,
        "f1": best["f1"],
        "precision": best["precision"],
        "recall": best["recall"],
        "confusion_matrix": {key: best[key] for key in ("tn", "fp", "fn", "tp")},
        "thresholds": thresholds,
        "test_metrics_by_policy": test_metrics,
        "flower_round_seconds": round_seconds,
        "flower_round_started_utc": round_started_utc,
        "flower_round_finished_utc": round_finished_utc,
        "max_client_train_seconds": max(c["train_seconds"] for c in client_metrics),
        "evaluation_blob_download_seconds": evaluation_download_seconds,
        "evaluation_blob_bytes": evaluation_blob_bytes,
        "test_inference_seconds": inference_seconds,
        "numeric_payload_bytes": sum(c["numeric_payload_bytes"] for c in client_metrics),
        "clients": sorted(client_metrics, key=lambda item: item["client_id"]),
    }
    results_root.mkdir(parents=True, exist_ok=True)
    model_dir = results_root / "models" / f"run_{context.run_id}"
    manifest_path = save_model(model_dir, forest, schema, threshold, context.run_id, mode)
    result["model_artifact"] = str(manifest_path)
    result_path = results_root / f"flower_seed{seed}_{mode}_clients{client_count}.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if artifact_url:
        pointer = publish_run(artifact_url, model_dir, result_path)
        result["artifact_blob_prefix"] = pointer["prefix"]
        result["artifact_latest_blob"] = f"latest-{mode}.json"
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
