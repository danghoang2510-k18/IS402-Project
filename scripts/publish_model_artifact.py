"""Publish an already completed Flower run to the artifacts container."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "flower-app"))
from fl_app.cloud_artifacts import publish_run


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--container-url", required=True)
    args = parser.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8"))
    model_dir = Path(result["model_artifact"]).parent
    pointer = publish_run(args.container_url, model_dir, args.result)
    print(json.dumps(pointer, indent=2))
