"""Flower ClientApp: train one local forest and send numeric tree arrays."""

from __future__ import annotations

import json
import os
import hashlib
import time
from io import BytesIO
from pathlib import Path

import pandas as pd
from flwr.app import Array, ArrayRecord, ConfigRecord, Context, Message, MetricRecord, RecordDict
from flwr.clientapp import ClientApp
from sklearn.ensemble import RandomForestClassifier

from fl_app.tree_codec import encode_forest, schema_hash
from fl_app.protocol import ROW_ID
from fl_app.blob_io import download_blob


app = ClientApp()


@app.train()
def train(msg: Message, context: Context) -> Message:
    config = msg.content["config"]
    if "CLIENT_ID" not in os.environ:
        raise RuntimeError("Set CLIENT_ID=1..N on this SuperNode VM before starting Flower")
    client_id = int(os.environ["CLIENT_ID"])
    if not 1 <= client_id <= int(config["num_clients"]):
        raise ValueError("CLIENT_ID is outside the configured client range")
    mode = str(config["mode"])
    trees = int(config["trees_per_client"])
    seed = int(config["seed"])
    data_root = Path(os.environ.get("PROJECT_DATA_ROOT", "data")).resolve()
    split_dir = data_root / "experiments" / f"split_seed_{seed}"
    schema = json.loads((split_dir / "feature_schema.json").read_text(encoding="utf-8"))
    features = schema["features"]
    if schema_hash(features) != str(config["schema_hash"]):
        raise ValueError("Client feature schema differs from the server schema")
    read_started = time.perf_counter()
    backend = os.environ.get("DATA_BACKEND", "vm")
    if backend == "blob":
        blob_url = os.environ.get("CLIENT_BLOB_URL")
        if not blob_url:
            raise RuntimeError("Set CLIENT_BLOB_URL when DATA_BACKEND=blob")
        source_bytes, blob_download_seconds = download_blob(blob_url)
        local = pd.read_csv(BytesIO(source_bytes))
        path_label = "client-specific Azure blob"
    elif backend == "vm":
        blob_download_seconds = 0.0
        partition_dir = split_dir / ("iid" if mode == "iid" else f"non_iid/alpha_{float(config.get('alpha', 0.5)):g}") / f"clients_{int(config['num_clients'])}"
        path = Path(os.environ.get("CLIENT_DATA_PATH", partition_dir / f"client_{client_id}.csv"))
        source_bytes = path.read_bytes()
        local = pd.read_csv(BytesIO(source_bytes))
        path_label = str(path)
    else:
        raise ValueError("DATA_BACKEND must be 'vm' or 'blob'")
    partition_sha256 = hashlib.sha256(source_bytes).hexdigest()
    data_read_seconds = time.perf_counter() - read_started
    if list(local.columns) != [ROW_ID, schema["target"]] + features or local.isna().any().any():
        raise ValueError(f"Invalid local partition: {path_label}")
    if set(local[schema["target"]].unique()) != {0, 1}:
        raise ValueError("Local partition must contain both classes")
    forest = RandomForestClassifier(
        n_estimators=trees,
        min_samples_leaf=5,
        max_depth=10,
        class_weight=None,
        max_features="sqrt",
        random_state=seed + client_id,
        n_jobs=1,
    )
    train_started = time.perf_counter()
    forest.fit(local[features], local[schema["target"]])
    train_seconds = time.perf_counter() - train_started
    payload = encode_forest(forest)
    array_record = ArrayRecord({key: Array(value) for key, value in payload.items()})
    return Message(
        content=RecordDict({
            "trees": array_record,
            "meta": ConfigRecord({"client_id": client_id, "schema_hash": schema_hash(features),
                                  "partition_sha256": partition_sha256}),
            "metrics": MetricRecord({
                "rows": len(local),
                "trees": trees,
                "numeric_payload_bytes": sum(value.nbytes for value in payload.values()),
                "train_seconds": train_seconds,
                "data_read_seconds": data_read_seconds,
                "blob_download_seconds": blob_download_seconds,
                "data_bytes": len(source_bytes),
            }),
        }),
        reply_to=msg,
    )
