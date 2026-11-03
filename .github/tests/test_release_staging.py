"""Exercise release staging from committed Git inputs, without publishing."""
from __future__ import annotations

import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
STAGE_SCRIPT = ROOT / "dev" / "stage-mission-control.ps1"
INPUTS = ("mission-control-template", "INTEGRATION_PROVENANCE.md", "docs/third_party/pstack/LICENSE")


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True, encoding="utf-8", env=clean_env())


def clean_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in list(env):
        if key in {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                   "GIT_OBJECT_DIRECTORY", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS",
                   "GH_TOKEN", "GITHUB_TOKEN"} or key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            env.pop(key, None)
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_SYSTEM": os.devnull, "GIT_TERMINAL_PROMPT": "0",
                "GIT_ALLOW_PROTOCOL": "file"})
    return env


def powershell_executable() -> str:
    found = shutil.which("pwsh")
    if not found:
        raise RuntimeError("PowerShell Core is required to test release staging")
    return found


class ReleaseStagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="worktrunk-release-stage-")
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        files = {
            ".gitignore": "target/\n__pycache__/\n",
            "mission-control-template/TEMPLATE.json": "{}\n",
            "mission-control-template/tools/mc.py": "# fixture\n",
            "mission-control-template/tools/wt_mission.py": "# fixture\n",
            "mission-control-template/tools/schema_subset.py": "# fixture\n",
            "mission-control-template/schemas/example.json": "{}\n",
            "mission-control-template/policies/example.md": "policy\n",
            "mission-control-template/tests/test_mission_control.py": "# fixture\n",
            "INTEGRATION_PROVENANCE.md": "attribution\n",
            "docs/third_party/pstack/LICENSE": "fixture license\n",
        }
        for name, content in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
        script = self.repo / "dev" / "stage-mission-control.ps1"
        script.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(STAGE_SCRIPT, script)
        for args in (("init",), ("config", "user.name", "Release Staging Test"),
                     ("config", "user.email", "release-staging@example.invalid"),
                     ("add", "."), ("commit", "-m", "fixture")):
            git(self.repo, *args)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def stage(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run([powershell_executable(), "-NoProfile", "-NonInteractive", "-File", "dev/stage-mission-control.ps1"], cwd=self.repo,
                              capture_output=True, text=True, encoding="utf-8", env=clean_env())

    def test_stage_contains_only_committed_inputs_and_retains_attribution(self) -> None:
        git(self.repo, "config", "core.autocrlf", "true")
        ignored = self.repo / "mission-control-template" / "tools" / "__pycache__" / "private.pyc"
        ignored.parent.mkdir(parents=True)
        ignored.write_bytes(b"ignored sentinel")
        result = self.stage()
        self.assertEqual(0, result.returncode, result.stderr)
        destination = self.repo / "target" / "flyby-dist" / "flyby-integration"
        tracked = git(self.repo, "ls-tree", "-r", "--name-only", "HEAD", "--", *INPUTS).stdout.splitlines()
        staged = {p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()}
        self.assertEqual(set(tracked), staged)
        for name in tracked:
            expected = subprocess.run(["git", "show", f"HEAD:{name}"], cwd=self.repo, check=True,
                                      capture_output=True, env=clean_env()).stdout
            self.assertEqual(expected, (destination / name).read_bytes(), name)
        self.assertNotIn("mission-control-template/tools/__pycache__/private.pyc", staged)
        self.assertIn("INTEGRATION_PROVENANCE.md", staged)
        self.assertIn("docs/third_party/pstack/LICENSE", staged)
        marker = destination / "keep.txt"
        marker.write_text("do not replace", encoding="utf-8")
        repeat = self.stage()
        self.assertNotEqual(0, repeat.returncode)
        self.assertEqual("do not replace", marker.read_text(encoding="utf-8"))

    def test_tracked_input_drift_blocks_before_staging(self) -> None:
        (self.repo / "mission-control-template" / "TEMPLATE.json").write_text("changed\n", encoding="utf-8")
        result = self.stage()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("uncommitted changes", result.stderr)
        self.assertFalse((self.repo / "target" / "flyby-dist" / "flyby-integration").exists())

    def test_hidden_index_flags_block_before_staging(self) -> None:
        path = "mission-control-template/TEMPLATE.json"
        for flag, clear in (("--assume-unchanged", "--no-assume-unchanged"),
                            ("--skip-worktree", "--no-skip-worktree")):
            with self.subTest(flag=flag):
                git(self.repo, "update-index", flag, path)
                (self.repo / path).write_text("hidden change\n", encoding="utf-8")
                result = self.stage()
                self.assertNotEqual(0, result.returncode)
                self.assertIn("index flags", result.stderr)
                self.assertFalse((self.repo / "target" / "flyby-dist" / "flyby-integration").exists())
                (self.repo / path).write_text("{}\n", encoding="utf-8", newline="\n")
                git(self.repo, "update-index", clear, path)

    def test_release_jobs_stage_before_dist_without_changing_admission(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release.yaml").read_text(encoding="utf-8")
        for job, next_job in (("plan", "build-local-artifacts"),
                              ("build-local-artifacts", "build-global-artifacts"),
                              ("build-global-artifacts", "host"), ("host", "announce")):
            block = workflow.split(f"\n  {job}:\n", 1)[1].split(f"\n  {next_job}:\n", 1)[0]
            self.assertEqual(1, block.count("./dev/stage-mission-control.ps1"), job)
            dist_call = re.search(r"(?m)^\s*dist (?:build|host|\$\{\{)", block)
            self.assertIsNotNone(dist_call, job)
            self.assertLess(block.index("./dev/stage-mission-control.ps1"), dist_call.start(), job)


if __name__ == "__main__":
    unittest.main(verbosity=2)
