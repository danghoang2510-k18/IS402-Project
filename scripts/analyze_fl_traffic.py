"""Summarize captured Flower TCP/8000 traffic for one ServerApp round.

Input is a private tshark CSV exported from a header-only server-NIC capture.
No packet contents or client training records are included in the output.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


FIELDS = ("frame.time_epoch", "ip.src", "ip.dst", "ip.len", "tcp.len")


def utc_epoch(value: str) -> float:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Flower round timestamp must include a UTC offset")
    return parsed.timestamp()


def parse_client(value: str) -> tuple[int, str]:
    client_id, sep, ip = value.partition("=")
    if not sep or not client_id.isdecimal() or not ip:
        raise argparse.ArgumentTypeError("Use --client-ip ID=PRIVATE_IP")
    return int(client_id), ip


def summarize(result: dict, packet_csv: Path, server_ip: str, client_ips: dict[int, str]) -> dict:
    start = utc_epoch(result["flower_round_started_utc"])
    end = utc_epoch(result["flower_round_finished_utc"])
    if end <= start:
        raise ValueError("Flower round end precedes start")
    expected_ids = set(range(1, int(result["num_clients"]) + 1))
    if set(client_ips) != expected_ids or len(set(client_ips.values())) != len(client_ips):
        raise ValueError("Provide one distinct private IP for every expected client")
    if server_ip in client_ips.values():
        raise ValueError("A client IP equals the server IP")

    by_ip = {ip: client_id for client_id, ip in client_ips.items()}
    counts = defaultdict(lambda: {"packets": 0, "ip_bytes": 0, "tcp_payload_bytes": 0})
    skipped_outside_round = 0
    with packet_csv.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not set(FIELDS).issubset(reader.fieldnames):
            raise ValueError(f"Expected tshark CSV columns: {FIELDS}")
        for row in reader:
            stamp = float(row["frame.time_epoch"])
            if stamp < start or stamp > end:
                skipped_outside_round += 1
                continue
            src, dst = row["ip.src"], row["ip.dst"]
            if src == server_ip and dst in by_ip:
                client_id, direction = by_ip[dst], "server_to_client"
            elif dst == server_ip and src in by_ip:
                client_id, direction = by_ip[src], "client_to_server"
            else:
                raise ValueError(f"Unexpected packet in round: {src} -> {dst}")
            ip_bytes, payload_bytes = int(row["ip.len"]), int(row["tcp.len"])
            if ip_bytes <= 0 or payload_bytes < 0 or payload_bytes > ip_bytes:
                raise ValueError("Invalid captured packet lengths")
            item = counts[(client_id, direction)]
            item["packets"] += 1
            item["ip_bytes"] += ip_bytes
            item["tcp_payload_bytes"] += payload_bytes

    clients = []
    numeric_by_client = {int(item["client_id"]): int(item["numeric_payload_bytes"])
                         for item in result["clients"]}
    if set(numeric_by_client) != expected_ids:
        raise ValueError("Flower JSON client payload list is incomplete")
    if sum(numeric_by_client.values()) != int(result["numeric_payload_bytes"]):
        raise ValueError("Client numeric payload sum differs from Flower round total")
    for client_id in sorted(client_ips):
        uploaded = counts[(client_id, "client_to_server")]
        downloaded = counts[(client_id, "server_to_client")]
        clients.append({
            "client_id": client_id,
            "private_ip": client_ips[client_id],
            "numeric_tree_array_bytes": numeric_by_client[client_id],
            "client_to_server": uploaded,
            "server_to_client": downloaded,
            "ip_bytes_total": uploaded["ip_bytes"] + downloaded["ip_bytes"],
            "tcp_payload_bytes_total": uploaded["tcp_payload_bytes"] + downloaded["tcp_payload_bytes"],
        })
    if any(client["ip_bytes_total"] == 0 for client in clients):
        raise ValueError("At least one client has no captured traffic in the Flower round")
    duration = end - start
    total_ip_bytes = sum(client["ip_bytes_total"] for client in clients)
    return {
        "run_id": str(result["run_id"]),
        "mode": result["mode"],
        "source_sha256": result.get("source_sha256"),
        "split_sha256": result.get("split_sha256"),
        "model_metrics": {key: result.get(key) for key in (
            "test_rows", "roc_auc", "average_precision", "f1", "precision", "recall"
        )},
        "round": 1,
        "round_started_utc": result["flower_round_started_utc"],
        "round_finished_utc": result["flower_round_finished_utc"],
        "round_duration_seconds": duration,
        "measurement": "server NIC, TCP/8000, IP packet length including retransmissions",
        "capture_scope": "Flower connection only; excludes Blob HTTPS, CLI loopback, and traffic outside the round",
        "numeric_tree_array_bytes": int(result["numeric_payload_bytes"]),
        "ip_bytes_total": total_ip_bytes,
        "ip_mib_total": total_ip_bytes / (1024 * 1024),
        "ip_mib_per_second": total_ip_bytes / (1024 * 1024) / duration,
        "tcp_payload_bytes_total": sum(client["tcp_payload_bytes_total"] for client in clients),
        "packets_total": sum(
            client[direction]["packets"]
            for client in clients for direction in ("client_to_server", "server_to_client")
        ),
        "skipped_packets_outside_round": skipped_outside_round,
        "clients": clients,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True, help="Flower JSON from the same run")
    parser.add_argument("--packet-csv", type=Path, required=True, help="tshark -T fields CSV")
    parser.add_argument("--server-ip", required=True)
    parser.add_argument("--client-ip", action="append", type=parse_client, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    client_map = dict(args.client_ip)
    if len(client_map) != len(args.client_ip):
        parser.error("Duplicate --client-ip ID")
    result = json.loads(args.result.read_text(encoding="utf-8"))
    report = summarize(result, args.packet_csv, args.server_ip, client_map)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "run_id": report["run_id"],
        "ip_bytes_total": report["ip_bytes_total"],
        "tcp_payload_bytes_total": report["tcp_payload_bytes_total"],
        "numeric_tree_array_bytes": report["numeric_tree_array_bytes"],
        "clients": len(report["clients"]),
    }, indent=2))
