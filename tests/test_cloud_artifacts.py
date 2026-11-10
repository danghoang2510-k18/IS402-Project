"""Exercise publication order and live model refresh without Azure credentials."""

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from sklearn.ensemble import RandomForestClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "flower-app"))
from fl_app.cloud_artifacts import LatestBlobModel, publish_run
from fl_app.model_artifact import save_model
from fl_app.tree_codec import decode_forests, encode_forest


class CloudArtifactTests(unittest.TestCase):
    def test_publish_and_refresh_only_verified_versions(self):
        storage = {}

        class ResourceExistsError(Exception):
            pass

        class FakeBlob:
            def __init__(self, url):
                self.url = url

            @classmethod
            def from_blob_url(cls, url, credential):
                return cls(url)

            def upload_blob(self, data, overwrite=False):
                if self.url in storage and not overwrite:
                    raise ResourceExistsError()
                storage[self.url] = bytes(data)

            def download_blob(self):
                return types.SimpleNamespace(readall=lambda: storage[self.url])

        modules = {
            "azure": types.ModuleType("azure"),
            "azure.core": types.ModuleType("azure.core"),
            "azure.core.exceptions": types.ModuleType("azure.core.exceptions"),
            "azure.identity": types.ModuleType("azure.identity"),
            "azure.storage": types.ModuleType("azure.storage"),
            "azure.storage.blob": types.ModuleType("azure.storage.blob"),
        }
        modules["azure.core.exceptions"].ResourceExistsError = ResourceExistsError
        modules["azure.identity"].DefaultAzureCredential = lambda: object()
        modules["azure.storage.blob"].BlobClient = FakeBlob
        base_url = "https://example.blob.core.windows.net/artifacts"
        x = pd.DataFrame({"a": [0, 0, 1, 1, 2, 2], "b": [1, 2, 1, 2, 1, 2]})
        fitted = RandomForestClassifier(n_estimators=3, random_state=42).fit(x, [0, 0, 1, 0, 1, 1])
        forest = decode_forests([encode_forest(fitted)], list(x.columns))
        schema = {"features": list(x.columns), "medians": {"a": 1, "b": 1.5},
                  "imputation": "median_fit_on_train_60pct"}

        def fake_download(url):
            return storage[url], 0.01

        with tempfile.TemporaryDirectory(dir=ROOT) as directory, patch.dict(sys.modules, modules), \
                patch("fl_app.cloud_artifacts.download_blob", side_effect=fake_download):
            root = Path(directory)

            def publish(run_id):
                model_dir = root / f"run_{run_id}"
                manifest = save_model(model_dir, forest, schema, 0.35, run_id, "iid")
                result_path = root / f"metrics_{run_id}.json"
                result_path.write_text(json.dumps({"mode": "iid", "model_artifact": str(manifest)}))
                return publish_run(base_url, model_dir, result_path)

            publish(1)
            provider = LatestBlobModel(base_url, root / "cache", refresh_seconds=30)
            self.assertEqual(provider.get()[1]["run_id"], 1)
            publish(2)
            provider._next_check = 0
            self.assertEqual(provider.get()[1]["run_id"], 2)
            self.assertEqual(provider.get()[2]["run_id"], 2)
            publish(3)
            storage[f"{base_url}/runs/3/forest.npz"] += b"corrupt"
            provider._next_check = 0
            self.assertEqual(provider.get()[1]["run_id"], 2)
            self.assertIn("checksum mismatch", provider.last_refresh_error)


if __name__ == "__main__":
    unittest.main()
