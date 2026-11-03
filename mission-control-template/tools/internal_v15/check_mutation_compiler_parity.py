#!/usr/bin/env python3
"""Generic parity gate: check-mode and materialization must accept the same mutation packet set."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COMPILER = HERE / "compile_mutation_frontier.py"


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("descriptor", type=Path)
    args = p.parse_args()
    descriptor = args.descriptor.resolve()
    try:
        desc = json.loads(descriptor.read_text(encoding="utf-8"))
        expected = [c["id"] for c in desc["cells"]]
    except Exception as exc:
        print(json.dumps({"state":"FAIL","stage":"DESCRIPTOR","error":str(exc)}, indent=2), file=sys.stderr)
        return 1

    dry = run([sys.executable, str(COMPILER), str(descriptor), "--check"])
    if dry.returncode != 0:
        print(json.dumps({"state":"FAIL","stage":"DRY_RUN","stdout":dry.stdout,"stderr":dry.stderr}, indent=2), file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="mission-control-compiler-parity-") as td:
        destination = Path(td) / "compiled"
        real = run([sys.executable, str(COMPILER), str(descriptor), "--destination", str(destination)])
        if real.returncode != 0:
            print(json.dumps({"state":"FAIL","stage":"MATERIALIZATION","stdout":real.stdout,"stderr":real.stderr}, indent=2), file=sys.stderr)
            return 1
        index_path = destination / desc["frontier_id"] / "INDEX.json"
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            actual = [c["cell_id"] for c in index["cells"]]
            if actual != expected:
                raise ValueError(f"compiled cell order/set mismatch expected={expected} actual={actual}")
        except Exception as exc:
            print(json.dumps({"state":"FAIL","stage":"INDEX_AUDIT","error":str(exc)}, indent=2), file=sys.stderr)
            return 1

    print(json.dumps({"state":"PASS","frontier_id":desc["frontier_id"],"cells":len(expected),"dry_run":"PASS","materialization":"PASS","parity":"PROVEN"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
