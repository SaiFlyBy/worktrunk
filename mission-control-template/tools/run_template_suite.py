#!/usr/bin/env python3
"""Run Mission Control template proof layers in canonical order and preserve evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
CATALOG = ROOT / "tests" / "TEST_LAYERS.json"
FAILURE_OUTPUT_LIMIT = 20000
DEFAULT_COMMAND_TIMEOUT_SECONDS = 900.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def git_text(*args: str, cwd: Path = REPO) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()
    except Exception:
        return None


def git_dirty_paths(repo: Path = REPO) -> list[str] | None:
    """Return content-level tracked/untracked dirt, ignoring stat-cache false positives."""
    tracked = git_text("diff", "--name-status", "HEAD", "--", cwd=repo)
    untracked = git_text("ls-files", "--others", "--exclude-standard", cwd=repo)
    if tracked is None or untracked is None:
        return None
    out = [line for line in tracked.splitlines() if line.strip()]
    out.extend(f"?? {line}" for line in untracked.splitlines() if line.strip())
    return out


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_command(command: list[str], environment_root: Path | None) -> list[str] | None:
    rendered: list[str] = []
    for token in command:
        if token == "${MISSION_ROOT}":
            if environment_root is None:
                return None
            rendered.append(str(environment_root.resolve()))
        elif token == "python":
            rendered.append(sys.executable)
        else:
            rendered.append(token)
    return rendered


def bounded_failure_output(text: str) -> str:
    if len(text) <= FAILURE_OUTPUT_LIMIT:
        return text
    omitted = len(text) - FAILURE_OUTPUT_LIMIT
    return f"[... {omitted} leading characters omitted ...]\n{text[-FAILURE_OUTPUT_LIMIT:]}"


def layer_blocks_overall(required: bool, state: str) -> bool:
    if state == "FAIL":
        return True
    return required and state.startswith("SKIPPED_")


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def execute_command(
    command: list[str],
    *,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    started_at = utc_now()
    started = time.perf_counter()
    state = "PASS"
    timed_out = False
    try:
        proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout_seconds)
        stdout = proc.stdout
        stderr = proc.stderr
        returncode = proc.returncode
        if returncode != 0:
            state = "FAIL"
    except subprocess.TimeoutExpired as exc:
        stdout = _timeout_text(exc.stdout)
        stderr = _timeout_text(exc.stderr)
        if stderr and not stderr.endswith("\n"):
            stderr += "\n"
        stderr += f"command timed out after {timeout_seconds:.3f} seconds\n"
        returncode = 124
        state = "TIMEOUT"
        timed_out = True
    elapsed = time.perf_counter() - started
    finished_at = utc_now()
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return {
        "command": command,
        "state": state,
        "timed_out": timed_out,
        "exit_code": returncode,
        "elapsed_seconds": elapsed,
        "started_at": started_at,
        "finished_at": finished_at,
        "stdout": stdout_path.name,
        "stderr": stderr_path.name,
        "stdout_sha256": sha256_file(stdout_path),
        "stderr_sha256": sha256_file(stderr_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--environment-mission-root", type=Path)
    parser.add_argument("--expected-sha")
    parser.add_argument("--require-clean", action="store_true")
    parser.add_argument("--command-timeout-seconds", type=float, default=DEFAULT_COMMAND_TIMEOUT_SECONDS)
    args = parser.parse_args()
    if args.command_timeout_seconds <= 0:
        parser.error("--command-timeout-seconds must be greater than zero")

    temporary: tempfile.TemporaryDirectory[str] | None = None
    if args.evidence_dir is None:
        temporary = tempfile.TemporaryDirectory(prefix="mission-control-proof-")
        evidence = Path(temporary.name)
    else:
        evidence = args.evidence_dir.resolve()

    started_at = utc_now()
    head = git_text("rev-parse", "HEAD")
    tree = git_text("rev-parse", "HEAD^{tree}")
    branch = git_text("symbolic-ref", "--quiet", "--short", "HEAD") or "(detached)"
    origin_url = git_text("config", "--get", "remote.origin.url")
    dirty_paths = git_dirty_paths()
    dirty = dirty_paths is None or bool(dirty_paths)
    preflight_errors: list[str] = []
    if head is None or tree is None:
        preflight_errors.append("unable to resolve candidate commit/tree identity")
    if args.expected_sha and head != args.expected_sha:
        preflight_errors.append(f"observed HEAD {head} != expected {args.expected_sha}")
    if dirty_paths is None:
        preflight_errors.append("unable to inspect repository worktree cleanliness")
    elif args.require_clean and dirty_paths:
        preflight_errors.append("repository worktree is dirty")

    evidence.mkdir(parents=True, exist_ok=True)
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    runner_identity = {
        "kind": "github_actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local",
        "runner_name": os.environ.get("RUNNER_NAME"),
        "runner_os": os.environ.get("RUNNER_OS") or platform.system(),
        "runner_arch": os.environ.get("RUNNER_ARCH") or platform.machine(),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "github_job": os.environ.get("GITHUB_JOB"),
        "github_workflow": os.environ.get("GITHUB_WORKFLOW"),
    }
    manifest = {
        "schema": "flyby/mission-control-proof-run/2",
        "started_at": started_at,
        "finished_at": None,
        "result": "RUNNING",
        "repository": str(REPO),
        "origin_url": origin_url,
        "branch": branch,
        "template_root": str(ROOT),
        "observed_head": head,
        "observed_tree": tree,
        "expected_head": args.expected_sha,
        "dirty": dirty,
        "dirty_paths": dirty_paths,
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "runner": runner_identity,
        "environment_mission_root": str(args.environment_mission_root.resolve()) if args.environment_mission_root else None,
        "command_timeout_seconds": args.command_timeout_seconds,
        "layer_order": catalog["order"],
    }
    write_json(evidence / "manifest.json", manifest)
    if preflight_errors:
        finished_at = utc_now()
        summary = {
            "state": "FAIL",
            "started_at": started_at,
            "finished_at": finished_at,
            "preflight_errors": preflight_errors,
            "layers": [],
        }
        write_json(evidence / "summary.json", summary)
        manifest["finished_at"] = finished_at
        manifest["result"] = "FAIL"
        write_json(evidence / "manifest.json", manifest)
        for error in preflight_errors:
            print(error, file=sys.stderr)
        return 1

    layer_results: list[dict[str, Any]] = []
    overall = "PASS"
    for layer in catalog["order"]:
        config = catalog["layers"][layer]
        layer_dir = evidence / layer
        layer_dir.mkdir(parents=True, exist_ok=True)
        command_results: list[dict[str, Any]] = []
        layer_state = "PASS"
        for index, raw_command in enumerate(config["commands"], start=1):
            command = render_command(raw_command, args.environment_mission_root)
            if command is None:
                layer_state = "SKIPPED_ENVIRONMENT_MISSING"
                break
            stdout_path = layer_dir / f"{index:02d}.stdout.txt"
            stderr_path = layer_dir / f"{index:02d}.stderr.txt"
            pending = {
                "command": command,
                "state": "RUNNING",
                "started_at": utc_now(),
            }
            write_json(layer_dir / f"{index:02d}.command.json", pending)
            result = execute_command(
                command,
                cwd=ROOT,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                timeout_seconds=args.command_timeout_seconds,
            )
            result["stdout"] = stdout_path.relative_to(evidence).as_posix()
            result["stderr"] = stderr_path.relative_to(evidence).as_posix()
            command_results.append(result)
            write_json(layer_dir / f"{index:02d}.command.json", result)
            write_json(
                layer_dir / "summary.json",
                {
                    "layer": layer,
                    "required": bool(config["required"]),
                    "state": "RUNNING" if result["state"] == "PASS" else "FAIL",
                    "commands": command_results,
                },
            )
            if result["state"] != "PASS":
                layer_state = "FAIL"
                break
        layer_result = {
            "layer": layer,
            "required": bool(config["required"]),
            "state": layer_state,
            "commands": command_results,
        }
        layer_results.append(layer_result)
        write_json(layer_dir / "summary.json", layer_result)
        if layer_blocks_overall(bool(config["required"]), layer_state):
            overall = "FAIL"
            break
        if layer_state == "FAIL":
            overall = "FAIL"
            break

    finished_at = utc_now()
    summary = {
        "state": overall,
        "started_at": started_at,
        "finished_at": finished_at,
        "layers": layer_results,
        "evidence_dir": str(evidence),
    }
    write_json(evidence / "summary.json", summary)
    manifest["finished_at"] = finished_at
    manifest["result"] = overall
    write_json(evidence / "manifest.json", manifest)
    lines = [f"Mission Control proof: {overall}"]
    for result in layer_results:
        lines.append(f"{result['layer']}: {result['state']}")
        for command in result["commands"]:
            lines.append(
                f"  state={command['state']} rc={command['exit_code']} elapsed={command['elapsed_seconds']:.3f}s :: "
                + " ".join(command["command"])
            )
            if command["state"] != "PASS":
                stdout = (evidence / command["stdout"]).read_text(encoding="utf-8")
                stderr = (evidence / command["stderr"]).read_text(encoding="utf-8")
                if stdout:
                    lines.append("  --- failing stdout ---")
                    lines.extend(f"  {line}" for line in bounded_failure_output(stdout).splitlines())
                if stderr:
                    lines.append("  --- failing stderr ---")
                    lines.extend(f"  {line}" for line in bounded_failure_output(stderr).splitlines())
    (evidence / "SUMMARY.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    if temporary is not None:
        print(f"temporary evidence: {evidence}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
