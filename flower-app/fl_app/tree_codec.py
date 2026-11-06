"""Portable numeric tree payload; no pickle deserialization over the network."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import numpy as np
from sklearn.ensemble import RandomForestClassifier


FIELDS = ("left", "right", "feature", "threshold", "value")


def schema_hash(features: list[str]) -> str:
    return hashlib.sha256(json.dumps(features, separators=(",", ":")).encode()).hexdigest()


def encode_forest(forest: RandomForestClassifier) -> dict[str, np.ndarray]:
    if not np.array_equal(forest.classes_, [0, 1]):
        raise ValueError("Both classes are required")
    payload: dict[str, np.ndarray] = {}
    for index, estimator in enumerate(forest.estimators_):
        tree = estimator.tree_
        payload[f"{index}.left"] = tree.children_left.astype(np.int64)
        payload[f"{index}.right"] = tree.children_right.astype(np.int64)
        payload[f"{index}.feature"] = tree.feature.astype(np.int64)
        payload[f"{index}.threshold"] = tree.threshold.astype(np.float64)
        payload[f"{index}.value"] = tree.value[:, 0, :].astype(np.float64)
    return payload


@dataclass
class NumericForest:
    trees: list[dict[str, np.ndarray]]
    feature_names: list[str]

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        # scikit-learn casts prediction inputs to float32 before traversing trees.
        x = np.asarray(features, dtype=np.float32)
        if x.ndim != 2 or x.shape[1] != len(self.feature_names):
            raise ValueError("Invalid feature matrix shape")
        probability = np.zeros((len(x), 2), dtype=np.float64)
        for tree in self.trees:
            node = np.zeros(len(x), dtype=np.int64)
            for _ in range(len(tree["left"])):
                active = np.flatnonzero(tree["left"][node] != -1)
                if len(active) == 0:
                    break
                current = node[active]
                go_left = x[active, tree["feature"][current]] <= tree["threshold"][current]
                node[active] = np.where(go_left, tree["left"][current], tree["right"][current])
            else:
                raise ValueError("Tree payload contains a cycle")
            values = tree["value"][node]
            probability += values / values.sum(axis=1, keepdims=True)
        return probability / len(self.trees)


def decode_forests(payloads: list[dict[str, np.ndarray]], features: list[str]) -> NumericForest:
    trees = []
    for payload in payloads:
        indices = {int(key.split(".", 1)[0]) for key in payload}
        if indices != set(range(len(indices))):
            raise ValueError("Tree indices must be contiguous")
        for index in sorted(indices):
            tree = {field: np.asarray(payload[f"{index}.{field}"]) for field in FIELDS}
            n = len(tree["left"])
            if n == 0 or any(len(tree[field]) != n for field in FIELDS):
                raise ValueError("Malformed tree payload lengths")
            if tree["value"].shape != (n, 2):
                raise ValueError("Tree leaf values must contain two classes")
            if np.any((tree["left"] < -1) | (tree["left"] >= n)) or np.any((tree["right"] < -1) | (tree["right"] >= n)):
                raise ValueError("Invalid child indices")
            internal = tree["left"] != -1
            if np.any((tree["right"] == -1) != ~internal):
                raise ValueError("Malformed leaf or branch")
            if np.any(tree["left"][internal] <= np.flatnonzero(internal)) or np.any(tree["right"][internal] <= np.flatnonzero(internal)):
                raise ValueError("Tree children must follow their parent")
            used = tree["feature"][tree["left"] != -1]
            if np.any((used < 0) | (used >= len(features))):
                raise ValueError("Invalid feature index")
            if not np.isfinite(tree["value"]).all() or np.any(tree["value"] < 0):
                raise ValueError("Invalid tree values")
            if np.any(tree["value"].sum(axis=1) <= 0):
                raise ValueError("Tree nodes must contain class values")
            trees.append(tree)
    if not trees:
        raise ValueError("No trees received")
    return NumericForest(trees, features)
