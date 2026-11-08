"""Prediction API for a saved federated forest."""

from __future__ import annotations

import csv
import json
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from fl_app.model_artifact import load_model


app = FastAPI(title="Federated Credit Risk API", version="1.0")


class PredictionRequest(BaseModel):
    features: dict[str, float | None]


@lru_cache(maxsize=1)
def _model():
    directory = os.environ.get("MODEL_DIR")
    if not directory:
        raise RuntimeError("Set MODEL_DIR to a saved model directory")
    return load_model(Path(directory))


@app.get("/healthz")
def healthz():
    try:
        _, manifest = _model()
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ready", "run_id": manifest["run_id"], "mode": manifest["mode"]}


@app.get("/dashboard")
def dashboard():
    """Return verified experiment metrics; never expose raw split data or paths."""
    results_root = Path(os.environ.get("PROJECT_RESULTS_ROOT", "results"))
    fl_path = Path(os.environ.get(
        "FL_RESULT_PATH", results_root / "flower_seed42_iid_clients5.json"
    ))
    central_path = Path(os.environ.get(
        "CENTRAL_METRICS_PATH",
        results_root / "protocol_v1/seed42_iid_clients5_trees20/test_metrics.csv",
    ))
    output: dict = {"fl": None, "central": None, "missing": []}
    if fl_path.is_file():
        result = json.loads(fl_path.read_text(encoding="utf-8"))
        output["fl"] = {key: result[key] for key in (
            "mode", "num_clients", "total_trees", "test_rows", "roc_auc",
            "average_precision", "f1", "precision", "recall", "confusion_matrix",
        )}
        output["fl"]["threshold"] = result["threshold_selected_on_validation"]
        output["fl"]["model_matches_loaded_artifact"] = False
        if result.get("model_artifact"):
            try:
                _, manifest = _model()
                if Path(result["model_artifact"]).resolve() == (Path(os.environ["MODEL_DIR"]) / "model.json").resolve():
                    output["fl"]["run_id"] = manifest["run_id"]
                    output["fl"]["model_matches_loaded_artifact"] = True
            except (OSError, ValueError, KeyError, RuntimeError):
                pass
    else:
        output["missing"].append("fl")
    if central_path.is_file():
        with central_path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        selected = next((row for row in rows if row["model"] == "centralized" and row["policy"] == "best_f1"), None)
        if selected is None:
            raise HTTPException(status_code=500, detail="Centralized metrics row is missing")
        output["central"] = {
            key: float(selected[key]) for key in
            ("roc_auc", "average_precision", "f1", "precision", "recall", "threshold")
        }
        output["central"]["confusion_matrix"] = {
            key: int(selected[key]) for key in ("tn", "fp", "fn", "tp")
        }
        output["central"]["test_rows"] = sum(output["central"]["confusion_matrix"].values())
        output["central"]["total_trees"] = 100
    else:
        output["missing"].append("central")
    return output


@app.post("/predict")
def predict(request: PredictionRequest):
    try:
        forest, manifest = _model()
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Model is unavailable") from exc
    features = manifest["features"]
    unknown = sorted(set(request.features) - set(features))
    if unknown:
        raise HTTPException(status_code=422, detail={"unknown_features": unknown})
    values = []
    imputed = []
    for name in features:
        value = request.features.get(name)
        if value is None:
            value = manifest["medians"][name]
            imputed.append(name)
        if isinstance(value, bool) or not np.isfinite(value):
            raise HTTPException(status_code=422, detail=f"Invalid value for {name}")
        values.append(float(value))
    probability = float(forest.predict_proba(np.asarray([values], dtype=np.float64))[0, 1])
    threshold = float(manifest["threshold"])
    return {
        "risk_probability": probability,
        "predicted_label": int(probability >= threshold),
        "threshold": threshold,
        "imputed_features": imputed,
        "model_run_id": manifest["run_id"],
        "mode": manifest["mode"],
    }
