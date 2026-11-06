"""Publish proof metadata while retaining original-fixture log contents privately."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def retain(private_root: Path, public_root: Path, expected_sha: str, provenance: dict) -> dict:
    canonical = private_root / "canonical"
    manifest = json.loads((canonical / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((canonical / "summary.json").read_text(encoding="utf-8"))
    if manifest["observed_head"] != expected_sha or manifest["expected_head"] != expected_sha:
        raise ValueError("private proof does not identify the approved candidate")
    if public_root.exists() and any(public_root.iterdir()):
        raise ValueError("public receipt destination is occupied")
    public_root.mkdir(parents=True, exist_ok=True)
    public_manifest = {key: manifest.get(key) for key in (
        "schema", "started_at", "finished_at", "result", "origin_url", "branch", "observed_head",
        "observed_tree", "expected_head", "dirty", "python", "platform", "runner", "layer_order",
    )}
    fixture = {key: provenance[key] for key in ("repository", "commit", "tree", "sealed_checksums")}
    layers = []
    for layer in summary.get("layers", []):
        commands = []
        for command in layer.get("commands", []):
            row = {key: command.get(key) for key in (
                "state", "exit_code", "timed_out", "elapsed_seconds", "started_at", "finished_at",
                "stdout_sha256", "stderr_sha256",
            )}
            raw = command["command"]
            row["command_sha256"] = hashlib.sha256(json.dumps(raw, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
            row["command"] = ["<verified-original-source>/archive/mission-control-v6" if index and raw[index-1] == "--mission-root" else value
                              for index, value in enumerate(raw)]
            commands.append(row)
        layers.append({"layer": layer["layer"], "required": layer["required"], "state": layer["state"], "commands": commands})
    receipt = {"state": summary["state"], "started_at": summary.get("started_at"),
               "finished_at": summary.get("finished_at"), "layers": layers,
               "log_contents_published": False, "private_evidence_retained": True,
               "runner_stdout_sha256": checksum(private_root / "runner.stdout.txt"),
               "runner_stderr_sha256": checksum(private_root / "runner.stderr.txt")}
    for name, value in (("manifest.json", public_manifest), ("summary.json", receipt), ("fixture-provenance.json", fixture)):
        (public_root / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-root", required=True, type=Path)
    parser.add_argument("--public-root", required=True, type=Path)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--provenance", required=True, type=Path)
    args = parser.parse_args()
    result = retain(args.private_root, args.public_root, args.candidate,
                    json.loads(args.provenance.read_text(encoding="utf-8")))
    print(json.dumps({"state": result["state"], "layers": [{"layer": row["layer"], "state": row["state"]} for row in result["layers"]],
                      "log_contents_published": False}))
