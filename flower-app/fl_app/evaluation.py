"""Shared validation thresholds and holdout metrics for central and FL forests."""

from __future__ import annotations

import numpy as np
from sklearn.metrics import (
    average_precision_score, brier_score_loss, confusion_matrix,
    precision_recall_curve, roc_auc_score,
)


def choose_thresholds(labels, scores, min_recall: float = 0.30) -> dict[str, float]:
    """Choose operating points on validation only, with deterministic ties."""
    precision, recall, candidates = precision_recall_curve(labels, scores)
    if not len(candidates):
        raise ValueError("Validation has no threshold candidates")
    p, r = precision[:-1], recall[:-1]
    f1 = 2 * p * r / np.maximum(p + r, 1e-12)
    eligible = np.flatnonzero(r >= min_recall)
    if not len(eligible):
        raise ValueError("No threshold reaches minimum recall")
    precision_choice = max(eligible, key=lambda i: (p[i], r[i]))
    return {
        "default": 0.5,
        "best_f1": float(candidates[np.argmax(f1)]),
        "precision_at_recall": float(candidates[precision_choice]),
    }


def evaluate(labels, scores, threshold: float) -> dict[str, float | int]:
    """Return one policy's metrics, all computed on the supplied holdout."""
    labels = np.asarray(labels)
    scores = np.asarray(scores, dtype=float)
    if labels.shape != scores.shape or not np.isfinite(scores).all():
        raise ValueError("Invalid labels or probabilities")
    predicted = (scores >= threshold).astype(int)
    tn, fp, fn, tp = (int(x) for x in confusion_matrix(labels, predicted, labels=[0, 1]).ravel())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    specificity = tn / (tn + fp) if tn + fp else 0.0
    return {
        "threshold": float(threshold),
        "roc_auc": float(roc_auc_score(labels, scores)),
        "average_precision": float(average_precision_score(labels, scores)),
        "brier_score": float(brier_score_loss(labels, scores)),
        "accuracy": (tp + tn) / len(labels),
        "balanced_accuracy": (recall + specificity) / 2,
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "false_positive_rate": fp / (fp + tn) if fp + tn else 0.0,
        "false_negative_rate": fn / (fn + tp) if fn + tp else 0.0,
        "positive_rate": float(np.mean(labels)),
        "predicted_positive_rate": float(np.mean(predicted)),
        "test_rows": len(labels),
        "tn": tn, "fp": fp, "fn": fn, "tp": tp,
    }
