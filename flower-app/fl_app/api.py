"""Prediction API for a saved federated forest."""

from __future__ import annotations

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
