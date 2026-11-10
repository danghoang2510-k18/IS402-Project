"""Contract checks for the shared split and numeric forest payload."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "flower-app"))
from fl_app.protocol import TARGET, ROW_ID, prepare_split, prepare_external_inference, partition_train, read_checked, sha256
from fl_app.tree_codec import encode_forest, decode_forests
from fl_app.model_artifact import save_model, load_model
from fl_app.evaluation import choose_thresholds, evaluate
from fl_app.blob_io import download_blob


class ProtocolTests(unittest.TestCase):
    def test_external_test_is_inference_only_and_uses_train_medians(self):
        frame = pd.DataFrame({f"feature_{i}": np.arange(100, dtype=float) for i in range(10)})
        frame[TARGET] = [0, 1] * 50
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            base = Path(directory)
            source = base / "train.csv"
            frame.to_csv(source, index=False)
            split = prepare_split(source, base / "experiments")
            before = sha256(split / "split_metadata.json")
            external = frame.iloc[:3].copy()
            external[TARGET] = np.nan
            external.loc[0, "feature_0"] = np.nan
            external.insert(0, "Unnamed: 0", [101, 102, 103])
            external_source = base / "cs-test.csv"
            external.to_csv(external_source, index=False)
            output = prepare_external_inference(external_source, split)
            prepared = pd.read_csv(output)
            schema = json.loads((split / "feature_schema.json").read_text())
            self.assertNotIn(TARGET, prepared)
            self.assertEqual(prepared[ROW_ID].tolist(), [101, 102, 103])
            self.assertEqual(prepared.loc[0, "feature_0"], schema["medians"]["feature_0"])
            self.assertEqual(before, sha256(split / "split_metadata.json"))

    def test_blob_backend_requires_https(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            download_blob("http://example.invalid/fl-client-1/client_1.csv")

    def test_shared_evaluation_is_consistent_with_confusion_counts(self):
        y = np.array([0, 0, 0, 1, 1, 1])
        scores = np.array([0.1, 0.4, 0.7, 0.2, 0.8, 0.9])
        thresholds = choose_thresholds(y, scores)
        self.assertEqual(set(thresholds), {"default", "best_f1", "precision_at_recall"})
        row = evaluate(y, scores, 0.5)
        self.assertEqual([row[k] for k in ("tn", "fp", "fn", "tp")], [2, 1, 1, 2])
        self.assertEqual(row["accuracy"], 4 / 6)
        self.assertAlmostEqual(row["balanced_accuracy"], 2 / 3)
        self.assertAlmostEqual(row["specificity"], 2 / 3)
        self.assertAlmostEqual(row["f1"], 2 / 3)

    def test_split_and_partition_contract(self):
        rng = np.random.default_rng(42)
        frame = pd.DataFrame(rng.normal(size=(500, 10)), columns=[f"feature_{i}" for i in range(10)])
        frame[TARGET] = np.tile([0] * 9 + [1], 50)
        frame.loc[::7, "feature_0"] = np.nan
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            base = Path(directory)
            source = base / "source.csv"
            frame.to_csv(source, index=False)
            split = prepare_split(source, base / "experiments")
            schema = json.loads((split / "feature_schema.json").read_text(encoding="utf-8"))
            parts = partition_train(split, clients=5)
            train, validation, test = (read_checked(split / f"{name}.csv", schema)
                                       for name in ("train", "validation", "test"))
            self.assertEqual([len(train), len(validation), len(test)], [300, 100, 100])
            self.assertFalse(set(train[ROW_ID]) & set(validation[ROW_ID]))
            self.assertFalse(set(train[ROW_ID]) & set(test[ROW_ID]))
            clients = [read_checked(parts / f"client_{i}.csv", schema) for i in range(1, 6)]
            self.assertEqual(set().union(*(set(c[ROW_ID]) for c in clients)), set(train[ROW_ID]))
            self.assertEqual(sum(map(len, clients)), len(train))
            self.assertEqual(sha256(split / "train.csv"),
                             json.loads((split / "split_metadata.json").read_text())["split_sha256"]["train"])

    def test_numeric_payload_matches_sklearn(self):
        x = pd.DataFrame({"a": [0, 0, 1, 1, 2, 2, 3, 3], "b": [1, 2, 1, 2, 1, 2, 1, 2]})
        y = [0, 0, 0, 1, 0, 1, 1, 1]
        model = RandomForestClassifier(n_estimators=5, random_state=42).fit(x, y)
        recovered = decode_forests([encode_forest(model)], list(x.columns))
        np.testing.assert_allclose(recovered.predict_proba(x.to_numpy()), model.predict_proba(x))
        self.assertEqual(len(recovered.trees), 5)

    def test_saved_model_preserves_predictions_and_detects_tampering(self):
        x = pd.DataFrame({"a": [0, 0, 1, 1, 2, 2], "b": [1, 2, 1, 2, 1, 2]})
        y = [0, 0, 1, 0, 1, 1]
        fitted = RandomForestClassifier(n_estimators=3, random_state=42).fit(x, y)
        forest = decode_forests([encode_forest(fitted)], list(x.columns))
        schema = {"features": list(x.columns), "medians": {"a": 1, "b": 1.5},
                  "imputation": "median_fit_on_train_60pct"}
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            artifact = Path(directory) / "model"
            save_model(artifact, forest, schema, 0.35, 123, "iid")
            restored, manifest = load_model(artifact)
            np.testing.assert_allclose(restored.predict_proba(x.to_numpy()),
                                       forest.predict_proba(x.to_numpy()))
            self.assertEqual(manifest["threshold"], 0.35)
            with (artifact / "forest.npz").open("ab") as stream:
                stream.write(b"tampered")
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_model(artifact)


if __name__ == "__main__":
    unittest.main()
