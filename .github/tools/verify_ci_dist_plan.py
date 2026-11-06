"""Reject generated release jobs outside the fork's Linux/Windows CI policy."""
import json
from pathlib import Path
import sys

TARGETS = {"aarch64-unknown-linux-musl", "x86_64-unknown-linux-musl", "x86_64-pc-windows-msvc"}


def validate(plan):
    rows = plan["ci"]["github"]["artifacts_matrix"]["include"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("release plan has no local artifact jobs")
    actual = []
    for row in rows:
        runner, targets = row["runner"], row["targets"]
        if not isinstance(runner, str) or not runner.startswith(("ubuntu-", "windows-")):
            raise ValueError("release plan contains a runner outside the Linux/Windows policy")
        if not isinstance(targets, list) or not targets or any(target not in TARGETS for target in targets):
            raise ValueError("release plan contains an unsupported CI target")
        actual.extend(targets)
    if len(actual) != len(set(actual)) or set(actual) != TARGETS:
        raise ValueError("release plan does not cover the three CI targets exactly once")


if __name__ == "__main__":
    validate(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
