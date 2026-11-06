"""Shared 60/20/20 credit-data protocol for notebooks and Flower nodes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

TARGET = "SeriousDlqin2yrs"
ROW_ID = "source_row_id"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_source(path: Path) -> tuple[pd.DataFrame, list[str]]:
    raw = pd.read_csv(path)
    raw = raw.drop(columns=[c for c in raw if str(c).startswith("Unnamed:")])
    if raw.columns.duplicated().any() or TARGET not in raw:
        raise ValueError("Missing target or duplicate columns")
    raw = raw.apply(pd.to_numeric, errors="raise")
    features = [name for name in raw if name != TARGET]
    if len(features) != 10 or raw[TARGET].isna().any() or set(raw[TARGET].unique()) != {0, 1}:
        raise ValueError("Expected 10 features and binary target 0/1")
    if raw[features].isna().all().any() or np.isinf(raw[features].to_numpy(float)).any():
        raise ValueError("Invalid feature values")
    raw = raw[[TARGET] + features]
    raw.insert(0, ROW_ID, np.arange(len(raw), dtype=np.int64))
    return raw, features


def prepare_split(source: Path, root: Path, seed: int = 42) -> Path:
    """Write one immutable-by-checksum split; keep duplicate content, not duplicate IDs."""
    raw, features = load_source(source)
    pool, test = train_test_split(raw, test_size=0.2, stratify=raw[TARGET], random_state=seed)
    train, validation = train_test_split(pool, test_size=0.25, stratify=pool[TARGET], random_state=seed)
    split_dir = root / f"split_seed_{seed}"
    split_dir.mkdir(parents=True, exist_ok=True)
    medians = train[features].median()
    if medians.isna().any():
        raise ValueError("Missing training median")
    schema = {"target": TARGET, "features": features,
              "imputation": "median_fit_on_train_60pct", "medians": medians.to_dict(), "seed": seed}
    schema_bytes = json.dumps(schema, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8")
    schema_path = split_dir / "feature_schema.json"
    schema_path.write_bytes(schema_bytes)
    hashes = {}
    for name, frame in (("train", train), ("validation", validation), ("test", test)):
        frame = frame.copy()
        frame[features] = frame[features].fillna(medians)
        if not np.isfinite(frame[features].to_numpy(float)).all():
            raise ValueError("Nonfinite values after imputation")
        path = split_dir / f"{name}.csv"
        frame.to_csv(path, index=False, float_format="%.17g")
        hashes[name] = sha256(path)
    ids = [set(frame[ROW_ID]) for frame in (train, validation, test)]
    if ids[0] & ids[1] or ids[0] & ids[2] or ids[1] & ids[2] or sum(map(len, ids)) != len(raw):
        raise AssertionError("Source row IDs overlap or are missing")
    manifest = {"protocol": "v1.0", "split_seed": seed, "source_sha256": sha256(source),
                "feature_schema_sha256": sha256(schema_path), "split_sha256": hashes,
                "rows": {"train": len(train), "validation": len(validation), "test": len(test)},
                "positive_rows": {"train": int(train[TARGET].sum()),
                                  "validation": int(validation[TARGET].sum()), "test": int(test[TARGET].sum())}}
    (split_dir / "split_metadata.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return split_dir


def partition_train(split_dir: Path, mode: str = "iid", alpha: float = 0.5,
                    clients: int = 5, seed: int = 42) -> Path:
    train = pd.read_csv(split_dir / "train.csv")
    rng = np.random.default_rng(seed)
    if mode not in {"iid", "non-iid"} or clients < 2:
        raise ValueError("Invalid partition configuration")
    buckets = [[] for _ in range(clients)]
    for label in (0, 1):
        label_ids = rng.permutation(np.flatnonzero(train[TARGET].to_numpy() == label))
        if mode == "iid":
            pieces = np.array_split(label_ids, clients)
        else:
            if alpha <= 0:
                raise ValueError("alpha must be positive")
            counts = rng.multinomial(len(label_ids), rng.dirichlet(np.full(clients, alpha)))
            pieces = np.split(label_ids, np.cumsum(counts)[:-1])
        for bucket, piece in zip(buckets, pieces):
            bucket.extend(piece.tolist())
    all_positions = np.concatenate([np.array(b, dtype=int) for b in buckets])
    if not np.array_equal(np.sort(all_positions), np.arange(len(train))):
        raise AssertionError("Client partitions overlap or omit rows")
    directory = split_dir / ("iid" if mode == "iid" else f"non_iid/alpha_{alpha:g}") / f"clients_{clients}"
    directory.mkdir(parents=True, exist_ok=True)
    summary = {"mode": mode, "alpha": alpha if mode != "iid" else None,
               "n_clients": clients, "partition_seed": seed,
               "split_sha256": sha256(split_dir / "split_metadata.json"), "clients": []}
    for client_id, positions in enumerate(buckets, 1):
        frame = train.iloc[sorted(positions)]
        if len(frame) < 2 or frame[TARGET].nunique() != 2:
            raise ValueError(f"Client {client_id} lacks both classes")
        path = directory / f"client_{client_id}.csv"
        frame.to_csv(path, index=False, float_format="%.17g")
        summary["clients"].append({"client_id": client_id, "rows": len(frame),
                                   "positive_rows": int(frame[TARGET].sum()), "sha256": sha256(path)})
    (directory / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return directory


def read_checked(path: Path, schema: dict) -> pd.DataFrame:
    frame = pd.read_csv(path)
    expected = [ROW_ID, TARGET] + schema["features"]
    if list(frame.columns) != expected or frame.isna().any().any():
        raise ValueError(f"Invalid split or partition schema: {path}")
    if not set(frame[TARGET].unique()).issubset({0, 1}) or frame[ROW_ID].duplicated().any():
        raise ValueError("Invalid target or duplicate source row IDs")
    if not np.isfinite(frame[schema["features"]].to_numpy(float)).all():
        raise ValueError("Nonfinite features")
    return frame
