"""Prepare cs-test.csv for inference without touching the labeled split."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "flower-app"))
from fl_app.protocol import prepare_external_inference

if __name__ == "__main__":
    output = prepare_external_inference(
        ROOT / "data" / "cs-test.csv",
        ROOT / "data" / "experiments" / "split_seed_42",
    )
    print(output)
