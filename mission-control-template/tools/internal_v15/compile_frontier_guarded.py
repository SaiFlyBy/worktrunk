#!/usr/bin/env python3
"""Canonical template frontier compiler entrypoint.

An instantiated mission must preserve this guarded routing pattern: coherence first,
mutation-descriptor preflight when applicable, disposable dry-run/materialization parity,
then an explicitly typed deterministic packet compiler.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def run(script: Path, *args: str) -> int:
    return subprocess.run([sys.executable, str(script), *args], cwd=ROOT).returncode


def main() -> int:
    if len(sys.argv) < 2:
        print("descriptor path is required", file=sys.stderr)
        return 2
    if run(HERE / "check_control_coherence.py") != 0:
        return 1

    descriptor = Path(sys.argv[1])
    try:
        schema = json.loads(descriptor.read_text(encoding="utf-8")).get("schema")
    except Exception as exc:
        print(f"invalid descriptor: {exc}", file=sys.stderr)
        return 2

    if schema == "flyby/mission-control-mutation-frontier-descriptor/1":
        if run(HERE / "check_mutation_descriptor.py", str(descriptor)) != 0:
            return 1
        if run(HERE / "check_mutation_compiler_parity.py", str(descriptor)) != 0:
            return 1
        compiler = HERE / "compile_mutation_frontier.py"
    else:
        compiler = HERE / "compile_frontier.py"
    return subprocess.run([sys.executable, str(compiler), *sys.argv[1:]], cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
