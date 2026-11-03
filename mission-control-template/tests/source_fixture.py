"""Locate the original, hash-bound template proof fixtures when supplied."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

SOURCE_COMMIT = "29efd0ffcac21717fd789da2c7020a7e02501e00"


def source_proof_repo(local_repo: Path) -> Path:
    requested = os.environ.get("MC_SOURCE_PROOF_REPO")
    if not requested:
        return local_repo
    source = Path(requested).resolve()
    env = os.environ.copy()
    for key in list(env):
        if key in {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                   "GIT_OBJECT_DIRECTORY", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"} or key.startswith("GIT_CONFIG_KEY_") or key.startswith("GIT_CONFIG_VALUE_"):
            env.pop(key, None)
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"})
    def git(*args: str) -> str:
        proc = subprocess.run(["git", "-C", str(source), *args], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", env=env)
        if proc.returncode:
            raise RuntimeError("Cannot verify the supplied original template source repository")
        return proc.stdout.strip()
    if Path(git("rev-parse", "--show-toplevel")).resolve() != source:
        raise RuntimeError("MC_SOURCE_PROOF_REPO must be the original repository root")
    if git("rev-parse", "HEAD").lower() != SOURCE_COMMIT:
        raise RuntimeError("MC_SOURCE_PROOF_REPO must be at the documented original source commit")
    origin = git("config", "--get", "remote.origin.url").lower().rstrip("/")
    if origin not in {"https://github.com/saiflyby/flybyrefactor.git",
                      "https://github.com/saiflyby/flybyrefactor",
                      "git@github.com:saiflyby/flybyrefactor.git",
                      "git@github.com:saiflyby/flybyrefactor"}:
        raise RuntimeError("MC_SOURCE_PROOF_REPO origin is not the original template repository")
    if git("status", "--porcelain=v1", "--untracked-files=all"):
        raise RuntimeError("MC_SOURCE_PROOF_REPO must be clean")
    return source
