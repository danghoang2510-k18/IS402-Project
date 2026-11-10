"""Verify accounting for one Flower TCP round without a live capture."""

import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from analyze_fl_traffic import summarize


class TrafficReportTests(unittest.TestCase):
    def test_direction_and_round_window(self):
        result = {
            "run_id": 123, "mode": "iid", "num_clients": 2,
            "numeric_payload_bytes": 900,
            "clients": [{"client_id": 1, "numeric_payload_bytes": 400},
                        {"client_id": 2, "numeric_payload_bytes": 500}],
            "flower_round_started_utc": "2026-01-01T00:00:00+00:00",
            "flower_round_finished_utc": "2026-01-01T00:00:10+00:00",
        }
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / "results") as directory:
            path = Path(directory) / "packets.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(("frame.time_epoch", "ip.src", "ip.dst", "ip.len", "tcp.len"))
                writer.writerows((
                    (1767225600.5, "10.0.0.2", "10.0.0.1", 120, 80),
                    (1767225601.5, "10.0.0.1", "10.0.0.2", 100, 60),
                    (1767225602.5, "10.0.0.3", "10.0.0.1", 130, 90),
                    (1767225603.5, "10.0.0.1", "10.0.0.3", 110, 70),
                    (1767225599.0, "10.0.0.2", "10.0.0.1", 999, 900),
                ))
            report = summarize(result, path, "10.0.0.1", {1: "10.0.0.2", 2: "10.0.0.3"})
        self.assertEqual(report["ip_bytes_total"], 460)
        self.assertEqual(report["tcp_payload_bytes_total"], 300)
        self.assertEqual(report["packets_total"], 4)
        self.assertEqual(report["skipped_packets_outside_round"], 1)
        self.assertEqual(report["clients"][0]["client_to_server"]["ip_bytes"], 120)
        self.assertEqual(report["clients"][1]["server_to_client"]["ip_bytes"], 110)

    def test_refuses_missing_round_timestamps(self):
        with self.assertRaises(KeyError):
            summarize({"num_clients": 1}, Path("unused.csv"), "10.0.0.1", {1: "10.0.0.2"})


if __name__ == "__main__":
    unittest.main()
