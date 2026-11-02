"""Behavioral tests for the scope-at-a-time Worktrunk bridge."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "wt_mission", Path(__file__).resolve().parents[1] / "tools" / "wt_mission.py"
)
bridge = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(bridge)


class PublishTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = "a" * 40
        self.head = "b" * 40
        self.report = {
            "state": "ACCEPTED", "kind": "MUTATION",
            "target": {"repository": "owner/repo", "base_sha": self.base},
            "result": {"target_outcomes": [{
                "repository": "owner/repo", "baseline_sha": self.base, "head_sha": self.head,
            }]},
            "workspace": {"path": "/workspace", "branch": "scope/one", "clean": True,
                          "head_sha": self.head, "origin": "https://github.com/owner/repo.git"},
        }
        self.args = bridge.argparse.Namespace(root="/mission", cell="M000", base="main",
                                              title="Scope one", body="Evidence", gh="gh")
        self.calls: list[list[str]] = []
        self.remote_branch = None
        self.remote_base = self.base
        self.push_fails = False
        self.gh_fails = False
        self.base_queries = 0
        self.change_base_after_push = False
        self.advanced_base_in_head = False
        self.open_prs: list[dict] = []

    def run_command(self, argv, **kwargs):
        self.calls.append(argv)
        if ("merge-base" in argv and self.remote_base != self.base and self.remote_base in argv
                and not self.advanced_base_in_head):
            return subprocess.CompletedProcess(argv, 1, "", "")
        if "push" in argv:
            if self.push_fails:
                return subprocess.CompletedProcess(argv, 1, "", "unknown push result")
            self.remote_branch = self.head
        if "list" in argv and "pr" in argv:
            if self.gh_fails:
                return subprocess.CompletedProcess(argv, 1, "", "forge unavailable")
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.open_prs), "")
        if "create" in argv and "pr" in argv:
            return subprocess.CompletedProcess(argv, 0, "https://github.com/owner/repo/pull/1\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def remote(self, repo, ref):
        if ref == "refs/heads/main":
            self.base_queries += 1
            return "d" * 40 if self.change_base_after_push and self.base_queries > 1 else self.remote_base
        return self.remote_branch

    def invoke(self):
        with patch.object(bridge, "scope_report", return_value=self.report), \
             patch.object(bridge, "ledger_entry", return_value={
                 "branch": "scope/one", "remote_url": "https://github.com/owner/repo.git",
                 "repository": "owner/repo", "base_sha": self.base}), \
             patch.object(bridge, "remote_head", side_effect=self.remote), \
             patch.object(bridge, "run", side_effect=self.run_command), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            bridge.publish(self.args)
            return json.loads(out.getvalue())

    def test_accepted_head_is_pushed_without_force_and_draft_pr_is_opened(self):
        result = self.invoke()
        self.assertEqual(result["state"], "DRAFT_PR_CREATED")
        push = next(call for call in self.calls if "push" in call)
        self.assertIn(self.head + ":refs/heads/scope/one", push)
        self.assertFalse(any("force" in part for part in push))
        pr = next(call for call in self.calls if "create" in call and "pr" in call)
        self.assertIn("--draft", pr)
        self.assertEqual(result["base_sha"], self.base)

    def test_changed_base_blocks_before_push(self):
        self.remote_base = "c" * 40
        with self.assertRaisesRegex(bridge.BridgeError, "remote base is contained"):
            self.invoke()
        self.assertFalse(any("push" in call or "create" in call for call in self.calls))

    def test_advanced_base_already_in_accepted_head_can_publish(self):
        self.remote_base = "c" * 40
        self.advanced_base_in_head = True
        result = self.invoke()
        self.assertEqual(result["state"], "DRAFT_PR_CREATED")
        self.assertEqual(result["base_sha"], self.remote_base)
        self.assertEqual(result["compiled_base_sha"], self.base)

    def test_dirty_or_changed_workspace_blocks_before_network(self):
        for field, value in (("clean", False), ("head_sha", "c" * 40)):
            with self.subTest(field=field):
                self.report["workspace"][field] = value
                with self.assertRaisesRegex(bridge.BridgeError, "Workspace"):
                    self.invoke()
                self.assertEqual(self.calls, [])
                self.report["workspace"][field] = True if field == "clean" else self.head

    def test_foreign_remote_branch_is_not_overwritten(self):
        self.remote_branch = "c" * 40
        with self.assertRaisesRegex(bridge.BridgeError, "different commit"):
            self.invoke()
        self.assertFalse(any("push" in call or "create" in call for call in self.calls))

    def test_uncertain_push_does_not_create_pr(self):
        self.push_fails = True
        with self.assertRaisesRegex(bridge.BridgeError, "reconcile"):
            self.invoke()
        self.assertFalse(any("create" in call for call in self.calls))

    def test_forge_lookup_failure_happens_before_push(self):
        self.gh_fails = True
        with self.assertRaisesRegex(bridge.BridgeError, "PR lookup failed"):
            self.invoke()
        self.assertFalse(any("push" in call or "create" in call for call in self.calls))

    def test_base_moving_during_push_preserves_branch_without_pr(self):
        self.change_base_after_push = True
        with self.assertRaisesRegex(bridge.BridgeError, "base changed after push"):
            self.invoke()
        self.assertEqual(self.remote_branch, self.head)
        self.assertFalse(any("create" in call for call in self.calls))

    def test_existing_matching_pr_is_returned_without_duplicate(self):
        self.remote_branch = self.head
        self.open_prs = [{"number": 8, "url": "https://github.com/owner/repo/pull/8",
                          "headRefOid": self.head}]
        result = self.invoke()
        self.assertEqual(result["state"], "EXISTING_PR")
        self.assertFalse(any("push" in call or "create" in call for call in self.calls))

    def test_unaccepted_scope_and_wrong_origin_are_rejected(self):
        self.report["state"] = "DISPATCHED"
        with self.assertRaisesRegex(bridge.BridgeError, "independently accepted"):
            self.invoke()
        self.report["state"] = "ACCEPTED"
        self.report["workspace"]["origin"] = "https://github.com/other/repo.git"
        with self.assertRaisesRegex(bridge.BridgeError, "Workspace custody"):
            self.invoke()
        self.assertEqual(self.calls, [])


class OriginTests(unittest.TestCase):
    def test_child_environment_drops_git_discovery_but_preserves_other_settings(self):
        source = {"GIT_DIR": "elsewhere", "GIT_WORK_TREE": "elsewhere",
                  "GIT_COMMON_DIR": "elsewhere", "GIT_INDEX_FILE": "elsewhere",
                  "GIT_OBJECT_DIRECTORY": "elsewhere", "WORKTRUNK_DIRECTIVE_CD_FILE": "elsewhere",
                  "GIT_CONFIG_COUNT": "1", "PATH": "retained"}
        child = bridge.child_environment(source)
        self.assertEqual(child, {"GIT_CONFIG_COUNT": "1", "PATH": "retained"})
        self.assertIn("GIT_DIR", source)

    def test_standard_origins_are_bound_to_repository(self):
        self.assertTrue(bridge.origin_matches("git@github.com:owner/repo.git", "owner/repo"))
        self.assertTrue(bridge.origin_matches("https://github.com/owner/repo", "owner/repo"))
        self.assertFalse(bridge.origin_matches("https://github.com/owner/other", "owner/repo"))
        self.assertFalse(bridge.origin_matches("C:/some/local/repo", "owner/repo"))


class RealGitPublishTests(unittest.TestCase):
    """Use a disposable local Git remote and a simulated forge, never live GitHub."""

    def test_publish_pushes_the_accepted_commit_to_a_real_git_remote(self):
        with tempfile.TemporaryDirectory(prefix="wt-mission-git-") as tmp:
            root = Path(tmp)
            bare, repo = root / "remote.git", root / "repo"
            test_env = bridge.child_environment(os.environ)
            for key in list(test_env):
                if key in {"GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"} or key.startswith("GIT_CONFIG_KEY_") or key.startswith("GIT_CONFIG_VALUE_"):
                    test_env.pop(key, None)
            test_env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                             "GIT_CONFIG_SYSTEM": os.devnull, "GIT_TERMINAL_PROMPT": "0"})
            def git_at(*argv):
                return subprocess.run(["git", *argv], check=True, capture_output=True, env=test_env,
                                      text=True, encoding="utf-8").stdout.strip()
            git_at("init", "--bare", str(bare))
            git_at("init", "-b", "main", str(repo))
            git_at("-C", str(repo), "config", "user.name", "Fixture")
            git_at("-C", str(repo), "config", "user.email", "fixture@example.invalid")
            (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
            git_at("-C", str(repo), "add", "tracked.txt")
            git_at("-C", str(repo), "commit", "-m", "base")
            base = git_at("-C", str(repo), "rev-parse", "HEAD")
            git_at("-C", str(repo), "remote", "add", "origin", str(bare))
            git_at("-C", str(repo), "push", "origin", "HEAD:refs/heads/main")
            git_at("-C", str(repo), "switch", "-c", "advance")
            (repo / "other.txt").write_text("accepted main\n", encoding="utf-8")
            git_at("-C", str(repo), "add", "other.txt")
            git_at("-C", str(repo), "commit", "-m", "advance main")
            advanced_base = git_at("-C", str(repo), "rev-parse", "HEAD")
            git_at("-C", str(repo), "push", "origin", "HEAD:refs/heads/main")
            git_at("-C", str(repo), "switch", "-c", "scope/one", base)
            (repo / "tracked.txt").write_text("scope\n", encoding="utf-8")
            git_at("-C", str(repo), "commit", "-am", "one scope")
            git_at("-C", str(repo), "merge", "--no-edit", "advance")
            head = git_at("-C", str(repo), "rev-parse", "HEAD")
            report = {
                "state": "ACCEPTED", "kind": "MUTATION",
                "target": {"repository": "owner/repo", "base_sha": base},
                "result": {"target_outcomes": [{"repository": "owner/repo",
                                                   "baseline_sha": base, "head_sha": head}]},
                # The real remote is local; the origin identity and forge are simulated here.
                "workspace": {"path": str(repo), "branch": "scope/one", "clean": True,
                              "head_sha": head, "origin": "https://github.com/owner/repo.git"},
            }
            args = bridge.argparse.Namespace(root=str(root), cell="M000", base="main",
                                             title="Scope", body="Evidence", gh="gh-fixture")
            real_run = bridge.run
            forge_calls = []
            def run_fixture(argv, **kwargs):
                if argv[0] == "gh-fixture":
                    forge_calls.append(argv)
                    output = "[]" if "list" in argv else "https://github.com/owner/repo/pull/1"
                    return subprocess.CompletedProcess(argv, 0, output, "")
                kwargs["env"] = test_env
                return real_run(argv, **kwargs)
            with patch.object(bridge, "scope_report", return_value=report), \
                 patch.object(bridge, "ledger_entry", return_value={
                     "branch": "scope/one", "remote_url": "https://github.com/owner/repo.git",
                     "repository": "owner/repo", "base_sha": base}), \
                 patch.object(bridge, "run", side_effect=run_fixture), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                bridge.publish(args)
            published = json.loads(output.getvalue())
            self.assertEqual(published["state"], "DRAFT_PR_CREATED")
            self.assertEqual(published["base_sha"], advanced_base)
            self.assertEqual(published["compiled_base_sha"], base)
            self.assertEqual(git_at("--git-dir", str(bare), "rev-parse", "refs/heads/scope/one"), head)
            self.assertTrue(any("create" in call and "--draft" in call for call in forge_calls))


class HandoffTests(unittest.TestCase):
    """A real Git graph with a simulated already-settled Mission Control record."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="wt-mission-handoff-test-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.mission, self.repo, self.source = root / "mission", root / "repo", root / "source"
        self.mission.mkdir()
        self.env = bridge.child_environment(os.environ)
        for key in list(self.env):
            if key in {"GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"} or key.startswith("GIT_CONFIG_KEY_") or key.startswith("GIT_CONFIG_VALUE_"):
                self.env.pop(key, None)
        self.env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                         "GIT_CONFIG_SYSTEM": os.devnull, "GIT_TERMINAL_PROMPT": "0"})
        self.git("init", "-b", "main", str(self.repo))
        self.git("-C", str(self.repo), "config", "user.name", "Fixture")
        self.git("-C", str(self.repo), "config", "user.email", "fixture@example.invalid")
        (self.repo / "base.txt").write_text("base\n", encoding="utf8")
        self.git("-C", str(self.repo), "add", "base.txt")
        self.git("-C", str(self.repo), "commit", "-m", "base")
        self.base = self.git("-C", str(self.repo), "rev-parse", "HEAD")
        self.git("-C", str(self.repo), "worktree", "add", "-b", "scope/one", str(self.source), self.base)
        (self.source / "scope.txt").write_text("scope\n", encoding="utf8")
        self.git("-C", str(self.source), "add", "scope.txt")
        self.git("-C", str(self.source), "commit", "-m", "accepted scope")
        self.head = self.git("-C", str(self.source), "rev-parse", "HEAD")
        (self.repo / "main change.txt").write_text("advanced\n", encoding="utf8")
        self.git("-C", str(self.repo), "add", "main change.txt")
        self.git("-C", str(self.repo), "commit", "-m", "advance main")
        self.advanced = self.git("-C", str(self.repo), "rev-parse", "HEAD")
        self.target = {"repository": "owner/repo", "base_sha": self.base, "owned_paths": ["scope.txt"]}
        self.cell = {"cell_id": "M000", "kind": "MUTATION", "dependencies": ["G000"],
                     "objective": "One complete scope", "acceptance": ["scope works"], "status": "PENDING",
                     "conflict_class": "write:scope", "resource_claims": ["scope-resource"],
                     "requirement_ids": ["R001"], "target": self.target,
                     "positive_verification": ["positive"], "negative_verification": ["negative"],
                     "rollback": "revert scope", "result_schema": "contracts/schemas/RESULT_SCHEMA.json"}
        self.record = {"state": "ACCEPTED", "attempt": 1}
        for kind in ("result", "context_receipt", "adjudication"):
            path = self.mission / (kind + ".json")
            path.write_text(json.dumps({"kind": kind}) + "\n", encoding="utf8")
            self.record[kind + "_ref"] = path.name
            self.record[kind + "_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.workspace = {"path": str(self.source), "branch": "scope/one", "clean": True,
                          "head_sha": self.head, "origin": "https://github.com/owner/repo.git"}
        self.report = {"target": self.target, "result": {"target_outcomes": [{"repository": "owner/repo",
                       "baseline_sha": self.base, "head_sha": self.head}]}, "workspace": self.workspace}
        self.entry = {"branch": "scope/one", "remote_url": self.workspace["origin"],
                      "repository": "owner/repo", "base_sha": self.base}
        self.packet = {"kind": "MUTATION", "target": self.target}
        self.args = bridge.argparse.Namespace(root=str(self.mission), cell="M000", successor="M002",
                                              frontier="F200", base_sha=self.advanced)
        self.compiled = []

    def git(self, *argv):
        return subprocess.run(["git", *argv], check=True, capture_output=True, env=self.env,
                              text=True, encoding="utf8").stdout.strip()

    def invoke(self):
        def compile_frontier(root, *argv):
            self.assertEqual(argv[0:2], ("compile", "--frontier"))
            self.compiled.append(json.loads(Path(argv[2]).read_text(encoding="utf8")))
            return ""
        with patch.dict(os.environ, self.env, clear=True), \
             patch.object(bridge, "cell_info", return_value=(self.cell, self.record, self.packet)), \
             patch.object(bridge, "scope_report", return_value=self.report), \
             patch.object(bridge, "ledger_entry", return_value=self.entry), \
             patch.object(bridge, "mc", side_effect=compile_frontier), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            bridge.handoff(self.args)
            return json.loads(out.getvalue())

    def test_successor_binds_original_evidence_and_base_changes(self):
        result = self.invoke()
        successor = self.compiled[0]["cells"][0]
        self.assertEqual(result["state"], "SUCCESSOR_COMPILED")
        self.assertEqual(result["source_head"], self.head)
        self.assertEqual(result["observed_base"], self.advanced)
        self.assertEqual(result["base_changed_paths"], ["main change.txt"])
        self.assertEqual(successor["target"], self.target)
        self.assertEqual(successor["resource_claims"], self.cell["resource_claims"])
        self.assertEqual(successor["requirement_ids"], self.cell["requirement_ids"])
        self.assertIn("M000", successor["dependencies"])
        self.assertTrue(set(self.cell["acceptance"] + bridge.HANDOFF_ACCEPTANCE) <= set(successor["acceptance"]))
        payload = json.loads(successor["objective"].split(bridge.HANDOFF_MARKER, 1)[1])
        self.assertEqual(payload["accepted_evidence"]["result"]["sha256"], self.record["result_sha256"])
        self.assertEqual(self.git("-C", str(self.source), "rev-parse", "HEAD"), self.head)
        self.assertEqual(self.git("-C", str(self.repo), "rev-parse", "HEAD"), self.advanced)

    def test_changed_source_or_tampered_evidence_is_rejected_before_compile(self):
        self.workspace["head_sha"] = self.advanced
        with self.assertRaisesRegex(bridge.BridgeError, "custody"):
            self.invoke()
        self.workspace["head_sha"] = self.head
        (self.mission / "result.json").write_text("tampered\n", encoding="utf8")
        with self.assertRaisesRegex(bridge.BridgeError, "evidence changed"):
            self.invoke()
        self.assertEqual(self.compiled, [])

    def test_handoff_rejects_unaccepted_or_already_contained_base(self):
        self.record["state"] = "DISPATCHED"
        with self.assertRaisesRegex(bridge.BridgeError, "independently accepted"):
            self.invoke()
        self.record["state"] = "ACCEPTED"
        self.args.base_sha = self.base
        with self.assertRaisesRegex(bridge.BridgeError, "already contains"):
            self.invoke()
        self.assertEqual(self.compiled, [])


if __name__ == "__main__":
    unittest.main()
