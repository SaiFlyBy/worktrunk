#!/usr/bin/env python3
"""Contract tests for exact-candidate proof-runner and CI workflow custody."""
from __future__ import annotations

import hashlib
import importlib.util
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from source_fixture import source_proof_repo

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
SOURCE_REPO = source_proof_repo(REPO)
RUNNER_PATH = ROOT / "tools" / "run_template_suite.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("mission_control_proof_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


class ProofRunnerContractSuite(unittest.TestCase):
    def test_01_required_skip_is_blocking(self) -> None:
        self.assertTrue(runner.layer_blocks_overall(True, "SKIPPED_ENVIRONMENT_MISSING"))
        self.assertFalse(runner.layer_blocks_overall(False, "SKIPPED_ENVIRONMENT_MISSING"))
        self.assertTrue(runner.layer_blocks_overall(True, "FAIL"))
        self.assertTrue(runner.layer_blocks_overall(False, "FAIL"))
        self.assertFalse(runner.layer_blocks_overall(True, "PASS"))

    def test_02_clean_gate_covers_entire_repository(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mcv-proof-clean-") as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "proof-runner@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Proof Runner Suite"], check=True)
            (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "base"], check=True, capture_output=True, text=True)
            self.assertEqual([], runner.git_dirty_paths(repo))
            workflow = repo / ".github" / "workflows" / "dirty.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text("name: dirty\n", encoding="utf-8")
            dirty = runner.git_dirty_paths(repo)
            self.assertIsNotNone(dirty)
            self.assertTrue(any(".github/workflows/dirty.yml" in row.replace("\\", "/") for row in dirty or []))
            workflow.unlink()
            self.assertEqual([], runner.git_dirty_paths(repo))

            tracked = repo / "tracked.txt"
            original = tracked.read_bytes()
            tracked.write_bytes(original)
            self.assertEqual([], runner.git_dirty_paths(repo), "same tracked bytes must remain content-clean")
            tracked.write_text("changed\n", encoding="utf-8")
            dirty = runner.git_dirty_paths(repo)
            self.assertTrue(any("tracked.txt" in row for row in dirty or []))

    def test_03_command_timeout_is_terminal_and_hashed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mcv-proof-timeout-") as tmp:
            root = Path(tmp)
            stdout = root / "stdout.txt"
            stderr = root / "stderr.txt"
            result = runner.execute_command(
                [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(1.0)"],
                cwd=root,
                stdout_path=stdout,
                stderr_path=stderr,
                timeout_seconds=0.05,
            )
            self.assertEqual("TIMEOUT", result["state"])
            self.assertTrue(result["timed_out"])
            self.assertEqual(124, result["exit_code"])
            self.assertTrue(result["started_at"])
            self.assertTrue(result["finished_at"])
            self.assertIn("timed out", stderr.read_text(encoding="utf-8"))
            self.assertEqual(hashlib.sha256(stdout.read_bytes()).hexdigest(), result["stdout_sha256"])
            self.assertEqual(hashlib.sha256(stderr.read_bytes()).hexdigest(), result["stderr_sha256"])

    def test_04_workflow_definition_guard_is_independent_and_pinned(self) -> None:
        guard = (SOURCE_REPO / ".github" / "workflows" / "mission-control-workflow-lint.yml").read_text(encoding="utf-8")
        self.assertIn('ACTIONLINT_VERSION: "1.7.12"', guard)
        self.assertIn('ACTIONLINT_SHA256: "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8"', guard)
        self.assertIn("sha256sum --check --strict -", guard)
        self.assertIn("rhysd/actionlint/releases/download", guard)
        self.assertIn(".github/workflows/mission-control-template.yml", guard)
        self.assertIn(".github/workflows/mission-control-workflow-lint.yml", guard)
        self.assertIn("pull_request:", guard)
        self.assertIn("persist-credentials: false", guard)

    def test_05_primary_workflow_forces_environment_and_trusted_local_proof(self) -> None:
        workflow = (SOURCE_REPO / ".github" / "workflows" / "mission-control-template.yml").read_text(encoding="utf-8")
        self.assertIn("--environment-mission-root archive/mission-control-v6", workflow)
        self.assertIn("trusted-self-hosted-template-suite:", workflow)
        self.assertIn("runs-on: [self-hosted, windows, x64]", workflow)
        self.assertIn("github.event.pull_request.head.repo.full_name == github.repository", workflow)
        self.assertEqual(2, workflow.count("fetch-depth: 0"), "both qualification checkout jobs require full history")
        self.assertEqual(2, workflow.count("Rehydrate hash-bound qualification fixtures"))
        self.assertEqual(
            2,
            workflow.count("['mission-control-template/examples/reference-mission','archive/mission-control-v6']"),
            "both qualification paths must discard both hash-bound fixture roots before rehydration",
        )
        self.assertEqual(
            2,
            workflow.count("mission-control-template/examples/reference-mission archive/mission-control-v6"),
            "both hosted and trusted reusable workspaces must restore both fixture roots through current attributes",
        )
        self_hosted = workflow.split("  trusted-self-hosted-template-suite:", 1)[1].split("  candidate-summary:", 1)[0]
        self.assertNotIn("shell: pwsh", self_hosted)
        self.assertGreaterEqual(self_hosted.count("shell: cmd"), 5)
        self.assertIn("needs: [template-suite, trusted-self-hosted-template-suite]", workflow)
        self.assertNotIn("PYTHONPYCACHEPREFIX: ${{ runner.temp }}/flyby-mcv-pycache\n    strategy:", workflow)

    def test_06_fork_bridge_workflow_tests_current_source(self) -> None:
        workflow = (REPO / ".github" / "workflows" / "mission-control-bridge.yaml").read_text(encoding="utf-8")
        self.assertIn("pull_request:", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("cargo build --locked --bin wt", workflow)
        self.assertIn("tests/test_wt_mission.py", workflow)
        self.assertIn("tests/test_runtime_state_machine.py", workflow)
        self.assertIn("tools' / 'test_template_v16.py", workflow)
        self.assertIn("WORKTRUNK_MC_TEST_HANDOFF", workflow)
        self.assertIn("ubuntu-24.04", workflow)
        self.assertIn("windows-2025", workflow)
        self.assertIn("runner: [self-hosted, Linux, X64, worktrunk-docker]", workflow)
        self.assertIn("runner: windows-2025", workflow)
        self.assertIn("name: bridge (${{ matrix.os }})", workflow)
        self.assertIn("github.repository_id == '1443337118'", workflow)
        self.assertIn("github.actor_id == '226779263'", workflow)
        self.assertIn("github.triggering_actor == 'SaiFlyBy'", workflow)
        self.assertIn("github.event.pull_request.head.repo.id == github.event.repository.id", workflow)
        self.assertNotIn("secrets.", workflow)
        actions = re.findall(r"^\s*uses:\s*([^\s#]+)", workflow, flags=re.MULTILINE)
        self.assertTrue(actions)
        for action in actions:
            if action == "./.github/actions/self-hosted-setup":
                # This composite comes from the same exact candidate checkout.
                setup = (REPO / ".github/actions/self-hosted-setup/action.yaml").read_text(encoding="utf-8")
                nested = re.findall(r"^\s*uses:\s*([^\s#]+)", setup, flags=re.MULTILINE)
                self.assertTrue(nested)
                for dependency in nested:
                    self.assertRegex(dependency, r"@[0-9a-f]{40}$", dependency)
                self.assertNotIn("secrets.", setup)
            else:
                self.assertRegex(action, r"@[0-9a-f]{40}$", action)


if __name__ == "__main__":
    unittest.main(verbosity=2)
