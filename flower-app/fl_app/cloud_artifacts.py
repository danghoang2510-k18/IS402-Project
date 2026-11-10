"""Publish versioned Flower artifacts and load the latest verified model."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fl_app.blob_io import download_blob
from fl_app.model_artifact import load_model

FILES = ("model.json", "forest.npz", "metrics.json")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _base_url(url: str) -> str:
    parsed = urlsplit(url.rstrip("/"))
    if parsed.scheme != "https" or not parsed.netloc or not parsed.path.strip("/") or parsed.query or parsed.fragment:
        raise ValueError("ARTIFACT_BLOB_BASE_URL must be an HTTPS container URL without SAS")
    return url.rstrip("/")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pointer(value: dict) -> dict:
    if value.get("format") != "fl-latest-v1":
        raise ValueError("Unsupported latest artifact pointer")
    if value.get("mode") not in {"iid", "non-iid"}:
        raise ValueError("Invalid model mode in latest artifact pointer")
    run_id = value.get("run_id")
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 0:
        raise ValueError("Invalid run ID in latest artifact pointer")
    if value.get("prefix") != f"runs/{run_id}":
        raise ValueError("Invalid artifact prefix")
    hashes = value.get("sha256")
    if not isinstance(hashes, dict) or set(hashes) != set(FILES):
        raise ValueError("Incomplete artifact checksums")
    if any(not isinstance(hashes[name], str) or not SHA256.fullmatch(hashes[name]) for name in FILES):
        raise ValueError("Invalid artifact checksum")
    return value


def publish_run(base_url: str, model_dir: Path, metrics_path: Path) -> dict:
    """Upload immutable files; update the mode pointer after verification."""
    from azure.core.exceptions import ResourceExistsError
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobClient

    base = _base_url(base_url)
    _, manifest = load_model(model_dir)
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    run_id = int(manifest["run_id"])
    if metrics.get("run_id", run_id) != run_id or metrics.get("mode") != manifest["mode"]:
        raise ValueError("Model and metrics belong to different runs")
    if metrics.get("model_artifact") and Path(metrics["model_artifact"]).resolve() != (model_dir / "model.json").resolve():
        raise ValueError("Metrics reference another model artifact")
    metrics["run_id"] = run_id
    metrics["artifact_blob_prefix"] = f"runs/{run_id}"
    contents = {
        "model.json": (model_dir / "model.json").read_bytes(),
        "forest.npz": (model_dir / "forest.npz").read_bytes(),
        "metrics.json": json.dumps(metrics, indent=2).encode("utf-8"),
    }
    pointer = _pointer({
        "format": "fl-latest-v1",
        "run_id": run_id,
        "mode": manifest["mode"],
        "prefix": f"runs/{run_id}",
        "sha256": {name: _digest(data) for name, data in contents.items()},
        "published_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    credential = DefaultAzureCredential()
    for name, data in contents.items():
        blob = BlobClient.from_blob_url(f"{base}/{pointer['prefix']}/{name}", credential=credential)
        try:
            blob.upload_blob(data, overwrite=False)
        except ResourceExistsError:
            pass
        if _digest(blob.download_blob().readall()) != pointer["sha256"][name]:
            raise ValueError(f"Artifact upload checksum mismatch: {name}")
    latest = BlobClient.from_blob_url(f"{base}/latest-{manifest['mode']}.json", credential=credential)
    latest.upload_blob(json.dumps(pointer, indent=2).encode("utf-8"), overwrite=True)
    return pointer


class LatestBlobModel:
    """Poll the mode pointer and swap verified models without API restart."""

    def __init__(self, base_url: str, cache_root: Path, refresh_seconds: float = 30.0,
                 mode: str = "iid"):
        self.base_url = _base_url(base_url)
        if mode not in {"iid", "non-iid"}:
            raise ValueError("MODEL_MODE must be iid or non-iid")
        self.mode = mode
        if refresh_seconds <= 0:
            raise ValueError("MODEL_REFRESH_SECONDS must be positive")
        self.refresh_seconds = refresh_seconds
        self.cache_root = cache_root
        self._lock = threading.RLock()
        self._current = None
        self._run_id = None
        self._next_check = 0.0
        self.last_refresh_error = None

    def get(self):
        with self._lock:
            if self._current is not None and time.monotonic() < self._next_check:
                return self._current
            self._next_check = time.monotonic() + self.refresh_seconds
            try:
                pointer = _pointer(json.loads(download_blob(f"{self.base_url}/latest-{self.mode}.json")[0]))
                if pointer["mode"] != self.mode:
                    raise ValueError("Latest pointer belongs to another model mode")
                if pointer["run_id"] != self._run_id:
                    self.cache_root.mkdir(parents=True, exist_ok=True)
                    with tempfile.TemporaryDirectory(prefix="model_", dir=self.cache_root) as temporary:
                        folder = Path(temporary)
                        for name in FILES:
                            data = download_blob(f"{self.base_url}/{pointer['prefix']}/{name}")[0]
                            if _digest(data) != pointer["sha256"][name]:
                                raise ValueError(f"Cloud artifact checksum mismatch: {name}")
                            (folder / name).write_bytes(data)
                        forest, manifest = load_model(folder)
                        metrics = json.loads((folder / "metrics.json").read_text(encoding="utf-8"))
                        if manifest["run_id"] != pointer["run_id"] or metrics.get("run_id") != pointer["run_id"]:
                            raise ValueError("Cloud artifact run IDs do not match")
                        if metrics.get("mode") != manifest["mode"]:
                            raise ValueError("Cloud artifact modes do not match")
                    self._current = (forest, manifest, metrics)
                    self._run_id = pointer["run_id"]
                self.last_refresh_error = None
            except Exception as exc:
                self.last_refresh_error = f"{type(exc).__name__}: {exc}"
                if self._current is None:
                    raise
            return self._current
