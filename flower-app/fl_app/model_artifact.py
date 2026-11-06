"""Save and load an aggregated numeric forest for inference."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from fl_app.tree_codec import FIELDS, NumericForest, decode_forests, schema_hash


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save_model(directory: Path, forest: NumericForest, schema: dict,
               threshold: float, run_id: int, mode: str) -> Path:
    """Write one immutable run directory; return its manifest path."""
    if directory.exists():
        raise FileExistsError(f"Model artifact already exists: {directory}")
    if not 0.0 <= threshold <= 1.0 or not np.isfinite(threshold):
        raise ValueError("Invalid decision threshold")
    features = schema["features"]
    if forest.feature_names != features or set(schema["medians"]) != set(features):
        raise ValueError("Model and preprocessing schema do not match")
    directory.mkdir(parents=True)
    arrays = {
        f"tree_{index}.{field}": tree[field]
        for index, tree in enumerate(forest.trees)
        for field in FIELDS
    }
    archive = directory / "forest.npz"
    np.savez_compressed(archive, **arrays)
    manifest = {
        "format": "numeric-forest-v1",
        "run_id": int(run_id),
        "mode": mode,
        "tree_count": len(forest.trees),
        "features": features,
        "schema_hash": schema_hash(features),
        "medians": {name: float(schema["medians"][name]) for name in features},
        "imputation": schema["imputation"],
        "threshold": float(threshold),
        "forest_sha256": _sha256(archive),
    }
    path = directory / "model.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def load_model(directory: Path) -> tuple[NumericForest, dict]:
    """Verify and load arrays without pickle deserialization."""
    manifest = json.loads((directory / "model.json").read_text(encoding="utf-8"))
    if manifest.get("format") != "numeric-forest-v1":
        raise ValueError("Unsupported model artifact format")
    features = manifest["features"]
    if manifest["schema_hash"] != schema_hash(features):
        raise ValueError("Model feature schema hash mismatch")
    if set(manifest["medians"]) != set(features):
        raise ValueError("Model preprocessing medians do not match features")
    archive = directory / "forest.npz"
    if _sha256(archive) != manifest["forest_sha256"]:
        raise ValueError("Model array checksum mismatch")
    with np.load(archive, allow_pickle=False) as saved:
        count = int(manifest["tree_count"])
        expected = {f"tree_{index}.{field}" for index in range(count) for field in FIELDS}
        if set(saved.files) != expected:
            raise ValueError("Model archive tree fields do not match manifest")
        payloads = [
            {f"0.{field}": saved[f"tree_{index}.{field}"] for field in FIELDS}
            for index in range(count)
        ]
    forest = decode_forests(payloads, features)
    return forest, manifest
