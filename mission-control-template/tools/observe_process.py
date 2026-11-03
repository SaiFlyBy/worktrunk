#!/usr/bin/env python3
"""External low-interference process observer for Mission Control characterization."""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover - optional enrichment
    psutil = None


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sample_process_tree(pid: int) -> dict[str, Any]:
    if psutil is None:
        return {"process_count": None, "rss_bytes": None, "cpu_seconds": None, "thread_count": None, "read_bytes": None, "write_bytes": None}
    try:
        root = psutil.Process(pid)
        processes = [root, *root.children(recursive=True)]
    except Exception:
        return {"process_count": 0, "rss_bytes": 0, "cpu_seconds": 0.0, "thread_count": 0, "read_bytes": 0, "write_bytes": 0}
    rss = 0
    cpu = 0.0
    threads = 0
    read_bytes = 0
    write_bytes = 0
    alive = 0
    for process in processes:
        try:
            with process.oneshot():
                rss += process.memory_info().rss
                times = process.cpu_times()
                cpu += float(times.user + times.system)
                threads += process.num_threads()
                io = process.io_counters()
                read_bytes += int(getattr(io, "read_bytes", 0))
                write_bytes += int(getattr(io, "write_bytes", 0))
                alive += 1
        except Exception:
            continue
    return {
        "process_count": alive,
        "rss_bytes": rss,
        "cpu_seconds": cpu,
        "thread_count": threads,
        "read_bytes": read_bytes,
        "write_bytes": write_bytes,
    }


def observer_health() -> dict[str, Any]:
    if psutil is None:
        return {"rss_bytes": None, "cpu_seconds": None}
    try:
        process = psutil.Process(os.getpid())
        times = process.cpu_times()
        return {"rss_bytes": process.memory_info().rss, "cpu_seconds": float(times.user + times.system)}
    except Exception:
        return {"rss_bytes": None, "cpu_seconds": None}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--interval-ms", type=int, default=20)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("command is required after --")
    if args.interval_ms < 5:
        parser.error("--interval-ms must be >= 5")

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    samples_path = output / "process_samples.ndjson"
    health_path = output / "observer_health.ndjson"
    stdout_path = output / "target.stdout.txt"
    stderr_path = output / "target.stderr.txt"
    prepared_wall = time.time()
    write_json(output / "manifest.json", {
        "schema": "flyby/mission-control-observer-run/1",
        "command": command,
        "cwd": os.getcwd(),
        "platform": platform.platform(),
        "python": sys.version,
        "observer_pid": os.getpid(),
        "sample_interval_ms": args.interval_ms,
        "psutil_enrichment": psutil is not None,
        "observer_prepared_unix": prepared_wall,
    })

    stats: dict[str, int | None] = {"peak_rss": None, "max_processes": None}
    stop_sampling = threading.Event()
    with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open("w", encoding="utf-8") as stderr_handle:
        started_wall = time.time()
        started_mono = time.perf_counter()
        process = subprocess.Popen(command, stdout=stdout_handle, stderr=stderr_handle, text=True)
        with samples_path.open("w", encoding="utf-8") as samples, health_path.open("w", encoding="utf-8") as health:
            def sample_loop() -> None:
                interval_seconds = args.interval_ms / 1000.0
                if stop_sampling.wait(interval_seconds):
                    return
                while not stop_sampling.is_set():
                    target = sample_process_tree(process.pid)
                    now = time.perf_counter()
                    samples.write(json.dumps({"elapsed_seconds": now - started_mono, **target}, sort_keys=True) + "\n")
                    health.write(json.dumps({"elapsed_seconds": now - started_mono, **observer_health()}, sort_keys=True) + "\n")
                    rss = target.get("rss_bytes")
                    count = target.get("process_count")
                    if isinstance(rss, int):
                        stats["peak_rss"] = max(int(stats["peak_rss"] or 0), rss)
                    if isinstance(count, int):
                        stats["max_processes"] = max(int(stats["max_processes"] or 0), count)
                    if stop_sampling.wait(interval_seconds):
                        return

            sampler = threading.Thread(target=sample_loop, name="mission-control-observer", daemon=True)
            sampler.start()
            exit_code = process.wait()
            duration = time.perf_counter() - started_mono
            stop_sampling.set()
            sampler.join(timeout=max(1.0, args.interval_ms / 1000.0 * 4))

    peak_rss = stats["peak_rss"]
    max_processes = stats["max_processes"]
    exit_record = {"exit_code": exit_code, "wall_seconds": duration, "started_unix": started_wall, "finished_unix": time.time()}
    write_json(output / "exit.json", exit_record)
    write_json(output / "summary.json", {
        "schema": "flyby/mission-control-observer-summary/1",
        **exit_record,
        "peak_rss_bytes": peak_rss,
        "max_process_count": max_processes,
        "psutil_enrichment": psutil is not None,
    })
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
